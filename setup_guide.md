# System Setup Guide

This guide details how to set up the **BioPipeline** application on a new system. The application uses a **hybrid architecture**:
- **Frontend/Server**: Runs on **Windows** (Python/Flask).
- **Pipeline Execution**: Runs on **WSL 2** (Ubuntu/Linux) using Conda environments.
- **Database**: mysql (Windows).

## Prerequisites

1.  **Operating System**: Windows 10 or Windows 11.
2.  **WSL 2**: Windows Subsystem for Linux enabled with an Ubuntu distribution installed.
3.  **Git**: Installed on Windows.
4.  **MySQL Server**: Installed on Windows and running.
5.  **Python 3.12+**: Installed on Windows.
6.  **Miniconda/Anaconda**: Installed **inside your WSL Ubuntu instance**.

---

## Part 1: Windows Setup (Server)

### 1. Clone the Repository
Clone the repository to a folder on your executable drive (e.g., `D:\gene` or `C:\Users\You\gene`).

### 2. Configure Environment (`.env`)
Create a `.env` file in the root directory. You can copy the structure below:
```ini
# Database Configuration
DB_HOST=localhost
DB_PORT=3306
DB_USER=root
# DB_PASSWORD=your_mysql_password
DB_NAME=gene_app

# Flask Security (Change this for production)
SECRET_KEY=your_secure_random_key_here
```
> **Note:** Ensure your MySQL server handles the credentials provided.

### 3. Install Windows Python Dependencies
Open a command prompt (cmd/powershell) in the project root and install the server dependencies:
```cmd
pip install -r requirements.txt
```

### 4. Initialize Database
Initialize the database and create a Super Admin user by running the helper script:
```cmd
python create_user.py
```
Follow the interactive prompts to create your first user. This script will automatically create the necessary database tables (`users`, `institutions`, `pipeline_runs`) if they don't exist.

---

## Part 2: WSL Setup (Pipeline Engine)

### 1. Open WSL
Open your Ubuntu terminal (WSL).

### 2. Verify Conda
Ensure conda is installed and initialized in WSL:
```bash
conda --version
```
*If not installed, download Miniconda for Linux and install it inside WSL.*

### 3. Install Pipeline Dependencies
Navigate to the project directory **from within WSL**.
*Example: If project is at `D:\gene`, the WSL path is likely `/mnt/d/gene`.*
```bash
cd /mnt/d/gene
bash install.sh
```
This script will:
1.  Create a Conda environment named `pipeline`.
2.  Install all bioinformatics tools (`flye`, `porechop`, `minimap2`, etc.) defined in `environment.yml`.
3.  Verify the installation of tools.

---

## Part 3: Running the Application

### 1. Start the Server
On Windows, simply execute the startup script:
```cmd
start.bat
```
Or manually:
```cmd
set FLASK_ENV=production
python main.py
```

### 2. Access the Application
Open your browser and navigate to:
`http://localhost:5000`

---

## Troubleshooting

### "WSL command not found" or Path Errors
The application forces a conversion of Windows paths to WSL paths (e.g., `C:\Data` -> `/mnt/c/Data`).
-   Ensure your WSL distribution is the default one.
-   Ensure you can run `wsl ls` from your Windows command prompt without errors.

### Database Connection Issues
-   Ensure MySQL service is running on Windows.
-   Check `.env` credentials.
-   If you get "Access denied", check your MySQL user permissions.

### Missing Tools in Diagnostics
If the "Check Tools" page shows tools as missing:
-   Ensure you ran `bash install.sh` inside WSL.
-   Ensure the conda environment `pipeline` was successfully created.
