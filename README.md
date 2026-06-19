# ApexDP - Cara Run

## Windows PowerShell

```powershell
git clone <test>
cd <test>

python -m venv .venv
.\.venv\Scripts\Activate.ps1

python -m pip install --upgrade pip
python -m pip install -r requirements.txt

python .\src\driver.py
```

Jika `Activate.ps1` ditolak:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

Jika `python` tidak dikenali:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
py -m pip install --upgrade pip
py -m pip install -r requirements.txt
py .\src\driver.py
```

Run tanpa activate:

```powershell
.\.venv\Scripts\python.exe .\src\driver.py
```

## Windows Command Prompt

```cmd
git clone <URL_REPOSITORY>
cd <NAMA_FOLDER_REPOSITORY>

python -m venv .venv
.venv\Scripts\activate.bat

python -m pip install --upgrade pip
python -m pip install -r requirements.txt

python src\driver.py
```

## macOS / Linux

```bash
git clone <URL_REPOSITORY>
cd <NAMA_FOLDER_REPOSITORY>

python3 -m venv .venv
source .venv/bin/activate

python -m pip install --upgrade pip
python -m pip install -r requirements.txt

python src/driver.py
```

Run tanpa activate:

```bash
.venv/bin/python src/driver.py
```

## Kalau Sudah Download ZIP

Masuk ke folder hasil extract, lalu jalankan command sesuai OS:

```powershell
cd <FOLDER_PROJECT>
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python .\src\driver.py
```
