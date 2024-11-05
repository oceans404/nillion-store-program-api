from fastapi import FastAPI, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse, StreamingResponse
import subprocess
import os
import tempfile
import shutil
import asyncio
import logging
from typing import Optional, Dict
import json
import uuid
import asyncio
import py_nillion_client as nillion
import uuid
import os
from pydantic import BaseModel

import sys
import platform
import datetime
import traceback
import pwd

from py_nillion_client import NodeKey, UserKey
from nillion_python_helpers import get_quote_and_pay, create_nillion_client, create_payments_config

from cosmpy.aerial.client import LedgerClient
from cosmpy.aerial.wallet import LocalWallet
from cosmpy.crypto.keypairs import PrivateKey

# Nillion Testnet Config: https://docs.nillion.com/network-configuration#testnet
nillion_testnet_default_config = {
    "cluster_id": 'b13880d3-dde8-4a75-a171-8a1a9d985e6c',
    "grpc_endpoint": 'https://testnet-nillion-grpc.lavenderfive.com',
    "chain_id": 'nillion-chain-testnet-1',
    "bootnodes": ['/dns/node-1.testnet-photon.nillion-network.nilogy.xyz/tcp/14111/p2p/12D3KooWCfFYAb77NCjEk711e9BVe2E6mrasPZTtAjJAPtVAdbye']
}

from dotenv import load_dotenv
load_dotenv()

try:
    private_key = PrivateKey(bytes.fromhex(os.getenv("NILLION_PRIVATE_KEY")))
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
    success: bool
    error: str
    program_id: Optional[str] = None
    json_content: Optional[Dict] = None

class NillionVersionResponse(BaseModel):
    nillion_installed: bool
    nillion_version: Optional[str] = None
    error: Optional[str] = None

async def check_nillion_installed() -> tuple[bool, str]:
    """
    Check if nillion is installed and return version
    Returns: (is_installed, version_or_error)
    """
    try:
        possible_paths = [
            "/root/.nilup/bin",  # Docker/Render path
            os.path.expanduser("~/.nilup/bin"),  # Local installation path
        ]
        
        nillion_executable = None
        nillion_path = None
        
        for path in possible_paths:
            potential_executable = os.path.join(path, "nillion")
            if os.path.exists(potential_executable):
                nillion_executable = potential_executable
                nillion_path = path
                logger.info(f"Found nillion in: {nillion_path}")
                break
                
        if not nillion_executable:
            logger.error("Nillion executable not found in any standard locations")
            return False, f"Nillion executable not found in paths: {', '.join(possible_paths)}"

        env = {
            **os.environ,
            "PATH": f"{nillion_path}:{os.environ.get('PATH', '')}"
        }

        process = await asyncio.create_subprocess_exec(
            nillion_executable,
            '--version',
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env
        )
        
        stdout, stderr = await process.communicate()
        
        if process.returncode == 0:
            version = stdout.decode().strip() or stderr.decode().strip()
            logger.info(f"Nillion version: {version}")
            return True, version
        else:
            error_message = stderr.decode().strip()
            logger.error(f"Error executing nillion: {error_message}")
            return False, error_message
            
    except Exception as e:
        logger.error(f"Exception in check_nillion_installed: {str(e)}")
        return False, str(e)

@app.get("/debug/nilup")
async def debug_nilup():
    """Debug endpoint to check nilup installation"""
    try:
        # Check various paths
        home = os.path.expanduser("~")
        paths_to_check = [
            os.path.expanduser("~/.nilup/bin"),
            "/opt/render/.nilup/bin",
            "/opt/render/project/.nilup/bin",
        ]
        
        # Try to run nilup manually
        try:
            nilup_result = subprocess.run(['nilup', '--version'], capture_output=True, text=True)
            nilup_output = nilup_result.stdout or nilup_result.stderr
        except Exception as e:
            nilup_output = f"Error running nilup: {str(e)}"

        # Try to run nillion manually
        try:
            nillion_result = subprocess.run(['nillion', '--version'], capture_output=True, text=True)
            nillion_output = f"Nillion version: {nillion_result.stdout}" if nillion_result.returncode == 0 else f"Nillion error: {nillion_result.stderr}"
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
            "nillion_test": nillion_output,
            "environment_vars": dict(os.environ)
        }
    except Exception as e:
        return {"error": str(e)}
    

@app.get("/debug/super")
async def debug_super():
    """Super verbose debug endpoint that checks everything"""
    debug_info = {}
    
    try:
        # System Information
        debug_info["system_info"] = {
            "current_time": datetime.datetime.now().isoformat(),
            "python_version": sys.version,
            "platform": platform.platform(),
            "architecture": platform.architecture(),
            "machine": platform.machine(),
            "processor": platform.processor(),
            "node": platform.node(),
        }

        # Directory Information
        debug_info["directories"] = {
            "current_working_dir": os.getcwd(),
            "home_dir": os.path.expanduser("~"),
            "absolute_path": os.path.abspath("."),
        }

        # Environment Variables
        debug_info["environment"] = {
            "all_env_vars": dict(os.environ),
            "important_vars": {
                "PATH": os.environ.get("PATH", "").split(":"),
                "HOME": os.environ.get("HOME"),
                "USER": os.environ.get("USER"),
                "PYTHONPATH": os.environ.get("PYTHONPATH"),
            }
        }

        # Nilup/Nillion Installation Checks
        possible_paths = [
            "/opt/render/.nilup/bin",
            "/opt/render/.nilup/bin/nillion",
            os.path.expanduser("~/.nilup/bin"),
            os.path.expanduser("~/.nilup/bin/nillion"),
            "/usr/local/bin/nillion",
        ]

        debug_info["installation_checks"] = {
            "possible_paths": {
                path: {
                    "exists": os.path.exists(path),
                    "is_file": os.path.isfile(path) if os.path.exists(path) else None,
                    "is_dir": os.path.isdir(path) if os.path.exists(path) else None,
                    "is_executable": os.access(path, os.X_OK) if os.path.exists(path) else None,
                    "permissions": oct(os.stat(path).st_mode)[-3:] if os.path.exists(path) else None,
                    "size": os.path.getsize(path) if os.path.exists(path) and os.path.isfile(path) else None,
                    "last_modified": datetime.datetime.fromtimestamp(os.path.getmtime(path)).isoformat() if os.path.exists(path) else None,
                }
                for path in possible_paths
            }
        }

        # Directory Contents
        for check_dir in ["/opt/render/.nilup", "/opt/render/.nilup/bin", os.path.expanduser("~/.nilup")]:
            if os.path.exists(check_dir) and os.path.isdir(check_dir):
                try:
                    contents = os.listdir(check_dir)
                    debug_info["installation_checks"][f"contents_of_{check_dir}"] = {
                        item: {
                            "is_file": os.path.isfile(os.path.join(check_dir, item)),
                            "is_executable": os.access(os.path.join(check_dir, item), os.X_OK),
                            "size": os.path.getsize(os.path.join(check_dir, item)),
                            "permissions": oct(os.stat(os.path.join(check_dir, item)).st_mode)[-3:]
                        }
                        for item in contents
                    }
                except Exception as e:
                    debug_info["installation_checks"][f"error_reading_{check_dir}"] = str(e)

        # Command Execution Tests
        debug_info["command_tests"] = {}
        
        commands_to_test = [
            ("which nillion", "Check nillion in PATH"),
            ("which nilup", "Check nilup in PATH"),
            ("/opt/render/.nilup/bin/nillion --version", "Direct nillion version check"),
            ("/opt/render/.nilup/bin/nilup --version", "Direct nilup version check"),
            ("ls -la /opt/render/.nilup/bin", "List nilup bin directory"),
        ]

        for cmd, description in commands_to_test:
            try:
                process = await asyncio.create_subprocess_shell(
                    cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                stdout, stderr = await process.communicate()
                debug_info["command_tests"][description] = {
                    "command": cmd,
                    "return_code": process.returncode,
                    "stdout": stdout.decode() if stdout else None,
                    "stderr": stderr.decode() if stderr else None,
                }
            except Exception as e:
                debug_info["command_tests"][description] = {
                    "command": cmd,
                    "error": str(e)
                }

        # File System Permissions
        render_paths = [
            "/opt/render",
            "/opt/render/.nilup",
            "/opt/render/.nilup/bin",
        ]
        debug_info["render_permissions"] = {
            path: {
                "exists": os.path.exists(path),
                "owner": get_owner(path) if os.path.exists(path) else None,
                "permissions": oct(os.stat(path).st_mode)[-3:] if os.path.exists(path) else None,
                "can_read": os.access(path, os.R_OK) if os.path.exists(path) else None,
                "can_write": os.access(path, os.W_OK) if os.path.exists(path) else None,
                "can_execute": os.access(path, os.X_OK) if os.path.exists(path) else None,
            }
            for path in render_paths
        }

    except Exception as e:
        debug_info["error"] = {
            "message": str(e),
            "type": type(e).__name__,
            "traceback": traceback.format_exc()
        }

    return debug_info

def get_owner(path):
    """Get the owner of a file/directory"""
    try:
        return pwd.getpwuid(os.stat(path).st_uid).pw_name
    except:
        return str(os.stat(path).st_uid)

async def store_program(
        compiled_nada_program_path
    ):
    try:
        cluster_id = nillion_testnet_default_config["cluster_id"]
        grpc_endpoint = nillion_testnet_default_config["grpc_endpoint"]
        chain_id = nillion_testnet_default_config["chain_id"]
        bootnodes = nillion_testnet_default_config["bootnodes"]
        
        # Create Nillion Client for user
        seed = str(uuid.uuid4())
        userkey = UserKey.from_seed(f"program-uploader-{seed}")
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
async def store_nada_program(file: UploadFile):
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
                    error="Command execution failed",
                    program_id=None,
                    json_content=None
                )
            
            base_filename = os.path.splitext(file.filename)[0]
            output_binary_filename = f'{base_filename}.nada.bin'
            output_json_filename = f'{base_filename}.nada.json'
            temp_output_bin_path = os.path.join(temp_dir, output_binary_filename)
            temp_output_json_path = os.path.join(temp_dir, output_json_filename)
            if os.path.exists(temp_output_json_path) and os.path.exists(temp_output_bin_path):
                resp = await store_program(temp_output_bin_path)
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
    is_installed, version_or_error = await check_nillion_installed()
    return {
        "nillion_installed": is_installed,
        "nillion_version": version_or_error if is_installed else None,
        "error": None if is_installed else version_or_error
    }