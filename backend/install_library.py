import subprocess
import sys


def install_library(package_name):
    print(f"⏳ Attempting to install {package_name}...")
    # This runs 'pip install package_name' via the system terminal
    subprocess.check_call([sys.executable, "-m", "pip", "install", package_name])
    print(f"✅ {package_name} installed successfully!")


# Example: Installing alembic automatically
try:
    import psycopg as almb
except ImportError:
    # If the library isn't found, install it on the fly
    install_library("psycopg[binary]")
    import psycopg as almb
