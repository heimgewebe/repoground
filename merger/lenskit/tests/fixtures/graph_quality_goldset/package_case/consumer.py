"""Package-import control: one package target must resolve locally."""

import package_case.pkg


def package_name() -> str:
    return package_case.pkg.__name__
