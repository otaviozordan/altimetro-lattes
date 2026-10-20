"""Prepara e abre o Altimetro em Windows, macOS ou Linux.

Na primeira vez cria um ambiente Python so do programa (.venv/) e instala as
bibliotecas de requirements.txt; nas seguintes, so abre. Se requirements.txt
mudar (uma versao nova do Altimetro), reinstala sozinho.

    python iniciar.py              prepara (se precisar) e abre
    python iniciar.py --instalar   reinstala as bibliotecas e abre
    python iniciar.py --so-preparar   so prepara o ambiente, sem abrir (testes)
"""
import hashlib
import os
import subprocess
import sys
import venv

AQUI = os.path.dirname(os.path.abspath(__file__))
VENV = os.path.join(AQUI, ".venv")
REQS = os.path.join(AQUI, "requirements.txt")
MARCA = os.path.join(VENV, "requirements.sha1")


def python_do_venv(janela=False):
    if os.name == "nt":
        return os.path.join(VENV, "Scripts", "pythonw.exe" if janela else "python.exe")
    return os.path.join(VENV, "bin", "python3")


def sem_tkinter():
    dica = {
        "darwin": "Instale o Python do site python.org (ja vem com o Tkinter) ou, com Homebrew: brew install python-tk",
        "linux": "Instale o Tkinter do sistema. Debian/Ubuntu: sudo apt install python3-tk python3-venv · "
                 "Fedora: sudo dnf install python3-tkinter · Arch: sudo pacman -S tk",
    }.get(sys.platform, "Reinstale o Python do site python.org marcando a opcao \"tcl/tk and IDLE\".")
    sys.exit("O Python deste computador esta sem o Tkinter (a parte que desenha janelas).\n" + dica)


def main():
    if sys.version_info < (3, 9):
        sys.exit(f"O Altimetro precisa do Python 3.9 ou mais novo (este e o {sys.version.split()[0]}). Baixe em https://www.python.org")
    try:
        import tkinter  # noqa: F401
    except ImportError:
        sem_tkinter()

    assinatura = hashlib.sha1(open(REQS, "rb").read()).hexdigest()
    instalado = open(MARCA).read().strip() if os.path.exists(MARCA) else ""
    if not os.path.exists(python_do_venv()) or instalado != assinatura or "--instalar" in sys.argv:
        print("Preparando o Altimetro (so na primeira vez; leva alguns minutos)...", flush=True)
        if not os.path.exists(python_do_venv()):
            try:
                venv.EnvBuilder(with_pip=True).create(VENV)
            except Exception as e:  # noqa: BLE001
                sys.exit(f"Nao deu para criar o ambiente em {VENV}: {e}\n"
                         "No Debian/Ubuntu, instale antes: sudo apt install python3-venv")
        py = python_do_venv()
        subprocess.check_call([py, "-m", "pip", "install", "--disable-pip-version-check", "-q", "--upgrade", "pip"])
        subprocess.check_call([py, "-m", "pip", "install", "--disable-pip-version-check", "-r", REQS])
        with open(MARCA, "w") as f:
            f.write(assinatura)
        print("Pronto.", flush=True)

    if "--so-preparar" in sys.argv:
        return
    programa = os.path.join(AQUI, "altimetro.py")
    if os.name == "nt":
        exe = python_do_venv(janela=True)
        if not os.path.exists(exe):
            exe = python_do_venv()
        subprocess.Popen([exe, programa], cwd=AQUI, creationflags=getattr(subprocess, "DETACHED_PROCESS", 0))
    else:
        os.chdir(AQUI)
        os.execv(python_do_venv(), [python_do_venv(), programa])


if __name__ == "__main__":
    main()
