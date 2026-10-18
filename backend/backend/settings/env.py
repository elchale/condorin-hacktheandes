from pathlib import Path

import environ

# For building paths use: BASE_DIR / 'subdir'
BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env(
    DEBUG=(bool, False),
)

environ.Env.read_env(str(BASE_DIR / '.env'))
