from fastapi import FastAPI, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import subprocess
import os
import tempfile
import shutil
import asyncio
import logging
from typing import List, Optional, Dict
import json
import uuid
import asyncio
import py_nillion_client as nillion
import uuid
import os
from pydantic import BaseModel


from py_nillion_client import NodeKey, UserKey
from nillion_python_helpers import get_quote_and_pay, create_nillion_client, create_payments_config

from cosmpy.aerial.client import LedgerClient
from cosmpy.aerial.wallet import LocalWallet
from cosmpy.crypto.keypairs import PrivateKey

# Nillion Testnet Config: https://docs.nillion.com/network-configuration#testnet
nillion_testnet_default_config = {
    "cluster_id": os.getenv("NILLION_CLUSTER_ID", 'b13880d3-dde8-4a75-a171-8a1a9d985e6c'),
    "grpc_endpoint": os.getenv("NILLION_NILCHAIN_GRPC", 'https://testnet-nillion-grpc.lavenderfive.com'),
    "chain_id": os.getenv("NILLION_NILCHAIN_CHAIN_ID", 'nillion-chain-testnet-1'),
    "bootnodes": [os.getenv("NILLION_BOOTNODE_MULTIADDRESS", '/dns/node-1.testnet-photon.nillion-network.nilogy.xyz/tcp/14111/p2p/12D3KooWCfFYAb77NCjEk711e9BVe2E6mrasPZTtAjJAPtVAdbye')] 
}

from dotenv import load_dotenv
load_dotenv()

try:
    private_key = PrivateKey(bytes.fromhex(os.getenv("NILLION_NILCHAIN_PRIVATE_KEY_0")))
except Exception as e:
    raise RuntimeError(f"Invalid Nilchain private key! Set your Nillion Testnet private key in the .env file.")


# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Nillion Testnet Program Uploader",
    description="Store a Nada Program on the Nillion Testnet"
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class StoreProgramSuccessResponse(BaseModel):
    success: bool
    program_id: str
    json_content: Optional[Dict] = None
    error: Optional[str] = None

class StoreProgramErrorResponse(BaseModel):
    success: bool = False
    error: str
    program_id: Optional[str] = None
    json_content: Optional[Dict] = None

class NillionVersionResponse(BaseModel):
    nillion_installed: bool
    nillion_version: Optional[str] = None
    error: Optional[str] = None
    cluster_id: str
    grpc_endpoint: str
    chain_id: str
    bootnodes: List[str]

# @app.get("/debug/nilup")
async def debug_nillion_version():
    """Debug endpoint to check nilup installation"""
    try:
        home = os.path.expanduser("~")
        paths_to_check = [
            os.path.expanduser("~/.nilup/bin"),
        ]
        
        try:
            nilup_result = subprocess.run(['nilup', '--version'], capture_output=True, text=True)
            nilup_output = nilup_result.stdout or nilup_result.stderr
        except Exception as e:
            nilup_output = f"Error running nilup: {str(e)}"

        try:
            nillion_result = subprocess.run(['nillion', '--version'], capture_output=True, text=True)
            nillion_output = nillion_result.stdout if nillion_result.returncode == 0 else None
        except Exception as e:
            nillion_output = f"Error running nillion: {str(e)}"

        return {
            "current_path": os.environ.get("PATH", ""),
            "home_directory": home,
            "paths_checked": {
                path: {
                    "exists": os.path.exists(path),
                    "contents": os.listdir(path) if os.path.exists(path) else "Directory not found",
                    "is_executable": os.access(path, os.X_OK) if os.path.exists(path) else False
                }
                for path in paths_to_check
            },
            "nilup_test": nilup_output,
            "nillion_sdk_version": nillion_output.strip()
        }
    except Exception as e:
        return {"error": str(e)}
    

async def store_program(
    compiled_nada_program_path: str,
    user_seed: Optional[str] = None
):
    try:
        cluster_id = nillion_testnet_default_config["cluster_id"]
        grpc_endpoint = nillion_testnet_default_config["grpc_endpoint"]
        chain_id = nillion_testnet_default_config["chain_id"]
        bootnodes = nillion_testnet_default_config["bootnodes"]
        
        # Create Nillion Client for user using seed if provided, otherwise generate a random seed
        seed = str(uuid.uuid4())
        userkey = UserKey.from_seed(user_seed) if user_seed else UserKey.from_seed(f"program-uploader-{seed}")
        nodekey = NodeKey.from_seed(seed)
        client = create_nillion_client(userkey, nodekey, bootnodes)
        user_id = client.user_id
        payments_config = create_payments_config(chain_id, grpc_endpoint)
        payments_client = LedgerClient(payments_config)

        payments_wallet = LocalWallet(private_key, prefix="nillion")

        program_name = os.path.splitext(os.path.basename(compiled_nada_program_path))[0].removesuffix('.nada')
        memo_store_program = f"petnet operation: store_program; program_name: {program_name}; user_id: {user_id}"
        receipt_store_program = await get_quote_and_pay(
            client,
            nillion.Operation.store_program(compiled_nada_program_path),
            payments_wallet,
            payments_client,
            cluster_id,
            memo_store_program,
        )

        program_id = await client.store_program(
            cluster_id, program_name, compiled_nada_program_path, receipt_store_program
        )

        return {"success": True, "program_id": program_id, "error": None}
    
    except Exception as e:
        logger.error(f"Error in store_program: {str(e)}")
        return {"success":False, "error":e["msg"], "program_id":None}

@app.post(
    "/store-program/",
    responses={
        200: {
            "description": "Successful operation",
            "model": StoreProgramSuccessResponse
        },
        400: {
            "description": "Bad Request - Invalid input or processing error",
            "model": StoreProgramErrorResponse
        }
    }
)
async def store_nada_program(file: UploadFile, user_seed: Optional[str] = None):
    """Upload a valid Nada program file, compile it to binary, and store the program on the Nillion Testnet; Returns the Program ID"""

    if not file.filename.endswith('.py'):
        raise HTTPException(
            status_code=400,
            detail="Not a valid Nada program - only (.py) files are allowed"
        )
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = os.path.join(temp_dir, file.filename)
            with open(file_path, 'wb') as f:
                shutil.copyfileobj(file.file, f)
            
            # compile program (pynadac command with the --generate-mir-json flag
            process = await asyncio.create_subprocess_exec(
                'pynadac',
                '--generate-mir-json',
                file_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=temp_dir,
                env={**os.environ, "PATH": f"{os.path.expanduser('~')}/.nilup/bin:{os.environ.get('PATH', '')}"}
            )
            
            stdout, stderr = await process.communicate()

            if process.returncode != 0:
                return StoreProgramErrorResponse(
                    success=False,
                    error=f"Failed to compile Nada program: {stderr.decode('utf-8')}",
                    program_id=None,
                    json_content=None
                )
            
            base_filename = os.path.splitext(file.filename)[0]
            output_binary_filename = f'{base_filename}.nada.bin'
            output_json_filename = f'{base_filename}.nada.json'
            temp_output_bin_path = os.path.join(temp_dir, output_binary_filename)
            temp_output_json_path = os.path.join(temp_dir, output_json_filename)
            if os.path.exists(temp_output_json_path) and os.path.exists(temp_output_bin_path):
                resp = await store_program(temp_output_bin_path, user_seed)
                with open(temp_output_json_path, mode="r") as json_file:
                    json_content = json_file.read()
                    json_data = json.loads(json_content)

                if not resp['success'] or resp['error'] is not None:
                    raise HTTPException(status_code=400, detail=resp['error'])
                else:
                    return StoreProgramSuccessResponse(
                        success=resp['success'],
                        program_id=resp['program_id'],
                        json_content=json_data,
                        error=None
                    )
            
    except Exception as e:
        logger.error(f"Error processing file: {str(e)}")
        return StoreProgramErrorResponse(
            success=False,
            program_id=None,
            json_content=None,
            error=str(e),
        )

@app.get("/check-nillion-version", response_model=NillionVersionResponse)
async def check_nillion_sdk_version():
    """Check the Nillion SDK version the Store Program API is using"""
    debug_output = await debug_nillion_version()
    nillion_installed = "nillion_sdk_version" in debug_output
    nillion_version = debug_output.get("nillion_sdk_version", None)
    return {
        "nillion_installed": nillion_installed,
        "nillion_version": nillion_version,
        "error": None if nillion_installed else "Nillion not installed",
        **nillion_testnet_default_config
    }