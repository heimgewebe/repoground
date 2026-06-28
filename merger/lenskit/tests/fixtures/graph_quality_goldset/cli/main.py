from core.service import run
import requests


def external_client_name() -> str:
    return requests.__name__


if __name__ == "__main__":
    run()
