"""scripts/check_env_example.py: classifica sem nunca imprimir valores (dados sintéticos)."""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('check_env_example', ROOT / 'scripts' / 'check_env_example.py')
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)

FAKE_SECRET = 'f00dbabe' * 16  # sintético


def run(tmp_path, capsys, content: str, name: str = '.env.example') -> tuple[int, str]:
    path = tmp_path / name
    path.write_text(content, encoding='utf-8')
    code = checker.main(['x', str(path)])
    return code, capsys.readouterr().out


def test_placeholders_and_safe_defaults_pass(tmp_path, capsys):
    code, out = run(tmp_path, capsys, '\n'.join([
        '# comentário', 'CORS_ORIGINS=http://localhost:5173', 'AFRIKA_DATABASE_URL=',
        'VERACODE_API_ID=', 'VERACODE_API_KEY=<preencher-localmente>', 'LOG_LEVEL=info', 'PORT=8000']))
    assert code == 0 and 'SEGURO' in out
    assert 'http://localhost:5173' not in out and 'preencher' not in out  # valores nunca impressos


def test_secret_like_values_fail_without_printing_them(tmp_path, capsys):
    code, out = run(tmp_path, capsys, '\n'.join([
        f'VERACODE_API_KEY={FAKE_SECRET}', 'VERACODE_API_ID=abc123real', f'# antigo: {FAKE_SECRET}',
        'OUTRO=valor-qualquer']))
    assert code == 1
    assert out.count('REVISAR') == 4
    assert FAKE_SECRET not in out and 'abc123real' not in out and 'valor-qualquer' not in out


def test_refuses_real_env_file(tmp_path, capsys):
    code, out = run(tmp_path, capsys, f'VERACODE_API_KEY={FAKE_SECRET}', name='.env')
    assert code == 2 and FAKE_SECRET not in out


def test_missing_file(tmp_path, capsys):
    assert checker.main(['x', str(tmp_path / 'nao-existe.env.example')]) == 2
