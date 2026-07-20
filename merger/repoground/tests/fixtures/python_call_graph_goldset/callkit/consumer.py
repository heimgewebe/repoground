import callkit.targets as target_mod
from callkit.targets import decorate, default_factory, grüßen, normalize as norm


def helper(value):
    return value


def direct(value):
    return helper(value)


def imported_alias(value):
    return norm(value)


def module_alias(value):
    return target_mod.normalize(value)


def loop(value):
    if value:
        return loop(value - 1)
    return 0


class Formatter:
    def format(self, value):
        return self.indent(value)

    def indent(self, value):
        return value


def invoke(callback, value):
    return callback(value)


@decorate(norm("präzise"))
def decorated(value=default_factory()):
    return value


def shadowed(normalize, value):
    return normalize(value)


def dynamic(value):
    return registry.handle(value)


def unicode_case(name):
    return grüßen(name)


def build_formatter():
    return Formatter()
