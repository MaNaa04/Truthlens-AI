from jose import jwt
from datetime import datetime, timedelta, timezone
import os
from dotenv import load_dotenv

load_dotenv()

SECRET_KEY = os.getenv("JWT_SECRET", "your_jwt_secret_here")
ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")

payload = {
    "sub": "postman_test_user_999", 
    "exp": datetime.now(timezone.utc) + timedelta(hours=1)
}

token = jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)
print('\nYOUR POSTMAN TOKEN:\n\n' + token + '\n')
