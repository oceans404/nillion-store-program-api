# Nillion Program Uploader

This is a set of FastAPI endpoints that allow you to store Nada programs like [addition.py](https://github.com/NillionNetwork/nada-by-example/blob/main/src/addition.py) to the Nillion Testnet.

## Create .venv and install requirements

Make sure you have Python 3.11 installed.

```
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Start the server

```
uvicorn main:app --reload
```

Visit http://localhost:8000/docs to see the API docs.
