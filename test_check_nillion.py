import os
import asyncio

async def check_nillion_installed() -> tuple[bool, str]:
    """
    Check if nillion is installed and return version
    Returns: (is_installed, version_or_error)
    """
    try:
        process = await asyncio.create_subprocess_exec(
            'nillion', '--version',
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env={**os.environ}
        )
        stdout, stderr = await process.communicate()
        
        if process.returncode == 0:
            version = stdout.decode().strip() or stderr.decode().strip()
            return True, version
        else:
            return False, stderr.decode().strip()
            
    except Exception as e:
        return False, str(e)

if __name__ == "__main__":
    result = asyncio.run(check_nillion_installed())
    print(result)
