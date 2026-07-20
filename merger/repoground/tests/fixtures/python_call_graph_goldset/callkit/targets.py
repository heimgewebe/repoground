def normalize(value):
    return value.strip()


def decorate(label):
    def apply(function):
        return function

    return apply


def default_factory():
    return "Standard"


def grüßen(name):
    return f"Hallo, {name}"
