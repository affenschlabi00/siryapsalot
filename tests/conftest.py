import json
import os

import pytest

ROOT = os.path.dirname(os.path.dirname(__file__))
EXAMPLES = os.path.join(ROOT, "examples")


@pytest.fixture(scope="session")
def build_dir(tmp_path_factory):
    return str(tmp_path_factory.mktemp("build"))


def load_example(name):
    with open(os.path.join(EXAMPLES, name)) as fh:
        return json.load(fh)
