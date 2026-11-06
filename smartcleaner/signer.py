"""Verify rules using a public key supplied by trusted application configuration."""

import base64
import json


def rule_payload(rule):
    if not isinstance(rule, dict):
        raise ValueError("Rule must be a JSON object")
    return json.dumps(rule, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


class AsymmetricRuleVerifier:
    @staticmethod
    def verify_rule_signature(rule_dict, signature_b64, public_key_pem=None):
        if not public_key_pem:
            return False, "No trusted public key configured"
        try:
            from cryptography.exceptions import InvalidSignature, UnsupportedAlgorithm
            from cryptography.hazmat.primitives import hashes, serialization
            from cryptography.hazmat.primitives.asymmetric import ed25519, padding, rsa
        except ImportError:
            return False, "Cryptography dependency unavailable"

        try:
            pem = public_key_pem.encode("ascii") if isinstance(public_key_pem, str) else public_key_pem
            key = serialization.load_pem_public_key(pem)
            signature = base64.b64decode(signature_b64, validate=True)
            payload = rule_payload(rule_dict)
            if isinstance(key, ed25519.Ed25519PublicKey):
                key.verify(signature, payload)
            elif isinstance(key, rsa.RSAPublicKey) and key.key_size >= 2048:
                key.verify(signature, payload, padding.PSS(
                    mgf=padding.MGF1(hashes.SHA256()), salt_length=32), hashes.SHA256())
            else:
                return False, "Unsupported public key"
            return True, "Valid signature"
        except (InvalidSignature, UnsupportedAlgorithm, ValueError, TypeError, RecursionError):
            return False, "Invalid key, rule or signature"


class RuleSigner:
    """Compatibility name for callers that supply an explicit Ed25519 signing key."""

    @staticmethod
    def sign_rule(rule_dict, private_key):
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        if not isinstance(private_key, Ed25519PrivateKey):
            raise ValueError("An explicit Ed25519 private key is required")
        return base64.b64encode(private_key.sign(rule_payload(rule_dict))).decode("ascii")

    @staticmethod
    def verify_rule(rule_dict, signature, public_key_pem=None):
        return AsymmetricRuleVerifier.verify_rule_signature(
            rule_dict, signature, public_key_pem)[0]
