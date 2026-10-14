"""Homologação REAL opt-in: carrega o `.env` da raiz e aplica o portão de `app.veracode.live_gate`.

Fora do portão, todos os testes deste diretório são ignorados com motivo seguro (sem valores).
Execute este diretório SEPARADO da suíte unitária (que desativa o `.env`).
"""
import os

import pytest

from app.env_loader import load_project_env
from app.veracode import live_gate


def pytest_addoption(parser):
    parser.addoption(live_gate.CLI_FLAG, action='store_true', default=False,
                     help='autoriza a homologação REAL com a Veracode (somente leitura; exige também '
                          f'{live_gate.LIVE_FLAG_VAR}=true e credenciais em {live_gate.DEFAULT_REF})')


def pytest_configure(config):
    load_project_env()  # nunca sobrescreve variáveis já definidas no sistema
    config._veracode_live_gate = live_gate.evaluate(
        os.environ, requested=config.getoption(live_gate.CLI_FLAG))


def pytest_collection_modifyitems(config, items):
    gate = config._veracode_live_gate
    if gate.enabled:
        return
    skip = pytest.mark.skip(reason=f'integração real desativada: {gate.reason}')
    for item in items:
        item.add_marker(skip)


@pytest.fixture(scope='session')
def veracode_live_gate(pytestconfig) -> live_gate.LiveGate:
    return pytestconfig._veracode_live_gate
