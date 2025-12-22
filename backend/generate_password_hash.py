"""Simple script to generate bcrypt hash for password"""
import bcrypt
import sys

password = sys.argv[1] if len(sys.argv) > 1 else "salon017"

# Bcrypt limitation: passwords cannot be longer than 72 bytes
password_bytes = password.encode('utf-8')
if len(password_bytes) > 72:
    password_bytes = password_bytes[:72]

# Generate salt and hash password using bcrypt
salt = bcrypt.gensalt()
hashed = bcrypt.hashpw(password_bytes, salt)

# Return as string (bcrypt hash is always ASCII-safe)
hashed_str = hashed.decode('utf-8')
print(hashed_str)




