# CRUD-INAHER

Proyecto de gestión de pedidos desarrollado con Django y SQLite.

---

## 🚀 Requisitos Previos

- Python 3.10 o superior
- Pip y Git

---

## 🛠️ Instalación y Puesta en Marcha

### 1. Clonar el repositorio y entrar al proyecto
```bash
git clone <URL_DEL_REPOSITORIO>
cd CRUD/CRUD-INAHER
```

### 2. Crear y activar el entorno virtual

- **En macOS / Linux:**
  ```bash
  python3 -m venv venv
  source venv/bin/activate
  ```

- **En Windows (PowerShell):**
  ```powershell
  python -m venv venv
  .\venv\Scripts\Activate.ps1
  ```
  *(Si da error de ejecución de scripts en PowerShell, ejecuta primero: `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass`)*

- **En Windows (CMD):**
  ```cmd
  python -m venv venv
  .\venv\Scripts\activate.bat
  ```

### 3. Instalar dependencias
```bash
pip install -r requirements.txt
```

### 4. Aplicar migraciones
```bash
python manage.py migrate
```

### 5. (Opcional) Crear superusuario para el panel de administración
```bash
python manage.py createsuperuser
```

### 6. Ejecutar el servidor
```bash
python manage.py runserver
```

El proyecto estará disponible en: [http://127.0.0.1:8000/](http://127.0.0.1:8000/)

---

## 🛑 Detener el entorno virtual
Para salir del entorno virtual, ejecuta:
```bash
deactivate
```