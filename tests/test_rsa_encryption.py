import pytest
import neurons.RSAEncryption as rsa

def test_generate_key_pair():
    """
    Test RSA key pair generation.
    
    Verifies that:
    - Both private and public keys are generated successfully
    - Keys are returned as strings
    - Keys have the correct PEM format headers
    """
    private_key, public_key = rsa.generate_key_pair()

    assert isinstance(private_key, str) and private_key.startswith("-----BEGIN PRIVATE KEY-----")
    assert isinstance(public_key, str) and public_key.startswith("-----BEGIN PUBLIC KEY-----")

def test_encrypt_decrypt():
    """
    Test the complete encryption and decryption cycle.
    
    Verifies that:
    - A message can be encrypted using the public key
    - The encrypted data is in bytes format
    - The original message can be recovered through decryption
    - The decrypted message matches the original input
    """
    private_key, public_key = rsa.generate_key_pair()
    
    plaintext = "Test message"
    ciphertext = rsa.encrypt_data(public_key.encode("utf-8"), plaintext)
    
    assert isinstance(ciphertext, bytes)
    
    decrypted_text = rsa.decrypt_data(private_key.encode("utf-8"), ciphertext)
    
    assert decrypted_text == plaintext

def test_decrypt_with_wrong_key():
    """
    Test decryption security with mismatched keys.
    
    Verifies that:
    - Attempting to decrypt a message with the wrong private key raises an exception
    - The encryption system properly enforces key pair matching
    """
    private_key1, public_key1 = rsa.generate_key_pair()
    private_key2, public_key2 = rsa.generate_key_pair()
    
    plaintext = "Another test message"
    ciphertext = rsa.encrypt_data(public_key1.encode("utf-8"), plaintext)
    
    with pytest.raises(Exception):
        rsa.decrypt_data(private_key2.encode("utf-8"), ciphertext)
