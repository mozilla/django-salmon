import re
import base64

from Crypto import Random
from Crypto.Hash import SHA256
from Crypto.PublicKey import RSA
from Crypto.Util import number

from django_salmon import utils

_WHITESPACE_RE = re.compile(r'\s+')
_KEY_RE = re.compile(
    r"""RSA\.
    (?P<mod>[^\.]+)
    \.
    (?P<exp>[^\.]+)
    (?:\.
    (?P<private_exp>[^\.]+)
    )?""",
    re.VERBOSE)


def base64_to_long(x):
    """Convert ``x`` from URL safe base64 encoding to a long integer."""
    return number.bytes_to_long(base64.urlsafe_b64decode(x))


def long_to_base64(x):
    """Convert ``x`` from a long integer to base64 URL safe encoding."""
    return base64.urlsafe_b64encode(number.long_to_bytes(x))


def extract_key_details(key):
    """
    Given a URL safe base64 encoded RSA key pair, return the modulus,
    public exponent and private exponent as a tuple of long integers.
    This is the format expected by ``Crypto.PublicKey.RSA.construct``.
    """
    match = _KEY_RE.match(key)
    b64_to_num = lambda a: number.bytes_to_long(base64.urlsafe_b64decode(a))
    return (
        b64_to_num(match.group('mod')),
        b64_to_num(match.group('exp')),
        b64_to_num(match.group('private_exp')),
    )


def generate(bits=1024):
    """
    Generate an RSA keypair and return the modulus, public exponent and private
    exponent as a URL safe base64 encoded strings.
    """
    rng = Random.new().read
    key = RSA.generate(bits, rng)
    # e - modulus, n - exponent, d - private exponent
    return (long_to_base64(key.e),
            long_to_base64(key.n),
            long_to_base64(key.d))


def make_esma_msg(data, keypair):
    h = SHA256.new(data).digest()
    magic_sha256_header = [0x30, 0x31, 0x30, 0xd, 0x6, 0x9, 0x60, 0x86,
                           0x48, 0x1, 0x65, 0x3, 0x4, 0x2, 0x1, 0x5, 0x0,
                           0x4, 0x20]
    encoded = ''.join([chr(c) for c in magic_sha256_header]) + h

    # Round up to next byte
    modulus_size = keypair.size()
    msg_size_bits = modulus_size + 8 - (modulus_size % 8)
    pad_string = chr(0xFF) * (msg_size_bits / 8 - len(encoded) - 3)
    return chr(0) + chr(1) + pad_string + chr(0) + encoded


def sign(data, keypair):
    """
    Sign the data. Most of this is taken verbatim from John Panzer's
    reference implementation:

    http://code.google.com/p/salmon-protocol/
    """
    rng = Random.new().read
    esma_msg = make_esma_msg(data, keypair)
    sig_long = keypair.sign(esma_msg, rng)[0]
    sig_bytes = number.long_to_bytes(sig_long)
    return base64.urlsafe_b64encode(sig_bytes).encode('utf-8')


def verify(author_uri, data, signed):
    """Verify that ``signed`` is ``data`` signed by ``author_uri``."""
    public_exp, mod = utils.get_public_key(author_uri)
    public_exp = base64_to_long(public_exp)
    mod = base64_to_long(mod)
    rsa = RSA.construct((public_exp, mod))
    data = utils.encode(data)
    putative = base64_to_long(signed.encode('utf-8'))
    esma = make_esma_msg(data, rsa)
    return rsa.verify(esma, (putative,))


def magic_envelope(raw_data, data_type, key):
    """Wrap the provided data in a magic envelope."""
    keypair = RSA.construct(
        (base64_to_long(key.public_exponent.encode('utf-8')),
         base64_to_long(key.mod.encode('utf-8')),
         base64_to_long(key.private_exponent.encode('utf-8'))))
    encoded_data = utils.encode(raw_data)
    signed = sign(encoded_data, keypair)
    return utils.create_magic_envelope(encoded_data, signed)
