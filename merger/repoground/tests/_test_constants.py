# merger/repoground/tests/_test_constants.py

# Semantically distinct: The generator configuration/provenance hash.
TEST_CONFIG_SHA256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"

# Semantically distinct: A dummy payload hash for file contents / artifacts.
TEST_ARTIFACT_SHA256 = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"


def make_generator_info(name="test", version="1.0", **extra):
    """
    Helps ensure that any generated tests calling `write_reports_v2`
    pass the required 64 hex lower-case config hash, preventing provenance failures.
    """
    base = {
        "name": name,
        "version": version,
        "config_sha256": TEST_CONFIG_SHA256
    }
    base.update(extra)
    return base
