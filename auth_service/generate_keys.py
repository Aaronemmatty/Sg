from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization

key = rsa.generate_private_key(public_exponent=65537, key_size=4096)

private_pem = key.private_bytes(
    serialization.Encoding.PEM,
    serialization.PrivateFormat.TraditionalOpenSSL,
    serialization.NoEncryption(),
).decode().strip().replace("\n", "\\n")

public_pem = key.public_key().public_bytes(
    serialization.Encoding.PEM,
    serialization.PublicFormat.SubjectPublicKeyInfo,
).decode().strip().replace("\n", "\\n")

print(f'JWT_PRIVATE_KEY="{private_pem}"')
print()
print(f'JWT_PUBLIC_KEY="{public_pem}"')