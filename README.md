# TeamFlow Backend

Backend service for the **TeamFlow** application — a scalable team collaboration and task management system inspired by Jira and Trello.  
This backend provides secure and efficient APIs for managing users, organizations, projects, tasks, and invitations with full authentication and role-based access control.

## 🔹 Introduction

**TeamFlow** enables organizations to collaborate effectively by providing tools for project tracking, task assignments, and workflow management.  
Built with **FastAPI** and **SQLModel**, it ensures high performance, maintainability, and clean architecture for modern web applications.

## 🔹 Features

- **User Authentication** (JWT-based secure login and registration)
- **Organization Management** (create and manage teams)
- **Project Management** (create, update, and assign projects)
- **Task Management** (track tasks, assign priorities and statuses)
- **Invitation System** (invite members to join organizations)
- **Role-Based Access Control** (admin and member permissions)
- **Email Notifications** (email-based invitation and updates)
- **Leave Management** (automatic initialization of leave types on startup)
- **Attendance Tracking** (check-in/check-out system with break management)
- **FastAPI Auto-Documentation** (Swagger and Redoc support)

## 🔹 Tech Stack

| Category | Technology |
|-----------|-------------|
| Framework | FastAPI |
| ORM | SQLModel |
| Database | PostgreSQL |
| Authentication | JWT (JSON Web Token) |
| Email Service | SMTP / Custom Email Service |
| Language | Python 3.11+ |

## 🔹 Folder Structure

```
backend/
├── main.py
├── core/
│   ├── database.py
│   ├── security.py
│   └── config.py
├── models/
│   └── models.py
├── schemas/
│   ├── user_schema.py
│   ├── project_schema.py
│   ├── task_schema.py
│   ├── invitation_schema.py
│   └── organization_schema.py
├── routes/
│   ├── auth.py
│   ├── projects.py
│   ├── tasks.py
│   ├── invitation.py
│   ├── users.py
│   └── organization.py
├── services/
│   └── email_service.py
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
├── wait-for-db.sh
├── .env
└── .env.example

````

## 🔹 Installation

Clone the repository:

```bash
git clone https://github.com/haroonsajid-ai/teamflow-backend.git
cd teamflow-backend
````

Create and activate a virtual environment:

```bash
python -m venv venv
source venv/bin/activate      # For Linux/Mac
venv\Scripts\activate         # For Windows
```

Install dependencies:

```bash
pip install -r requirements.txt
```

## 🔹 Environment Setup

Create a `.env` file in the root directory with the following variables:

```
DATABASE_URL=postgresql+psycopg2://user:password@localhost:5432/teamflow_db
SECRET_KEY=your_secret_key
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=60
EMAIL_HOST=smtp.yourmail.com
EMAIL_PORT=587
EMAIL_USER=your_email@example.com
EMAIL_PASSWORD=your_email_password
```

## 🔹 Running the Server

Start the FastAPI application using Uvicorn:

```bash
uvicorn main:app --reload
```

The API will be available at:
**[http://127.0.0.1:8000](http://127.0.0.1:8000)**

Swagger UI for interactive documentation:
**[http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)**

Redoc documentation:
**[http://127.0.0.1:8000/redoc](http://127.0.0.1:8000/redoc)**

---

## 🔹 Automatic Leave Data Initialization

**NEW!** The backend now automatically initializes leave types for all organizations on startup.

### 🚀 How It Works

- On every deploy (Render, Railway, Fly.io, etc.), the application:
  1. Creates all database tables
  2. Seeds default leave types for any organization that doesn't have them
  3. Logs all operations for debugging

### ✅ Guarantees

- **Idempotent**: Safe to run multiple times, never creates duplicates
- **Organization-Aware**: Each organization gets its own leave types
- **Production-Ready**: Comprehensive error handling and logging
- **Zero Manual Work**: No scripts to run, works automatically

### 📊 Default Leave Types

Each organization gets these 4 leave types:

- Annual Leave (20 days)
- Sick Leave (10 days)
- Personal Leave (5 days)
- Unpaid Leave (unlimited)

### 🩺 Health Check

Verify leave types initialization:

```bash
curl https://your-app.onrender.com/health/leave-types
```

### 📚 Full Documentation

See [LEAVE_INITIALIZATION.md](LEAVE_INITIALIZATION.md) for complete details on:

- How the system works
- Testing and verification
- Troubleshooting
- Customization

---

## 🔹 API Endpoints Overview

| Endpoint              | Method              | Description                            |
| --------------------- | ------------------- | -------------------------------------- |
| `/auth/register`      | POST                | Register a new user                    |
| `/auth/login`         | POST                | Authenticate user and return JWT token |
| `/users/me`           | GET                 | Retrieve current authenticated user    |
| `/organizations/`     | POST                | Create a new organization              |
| `/projects/`          | GET/POST/PUT/DELETE | Manage projects                        |
| `/tasks/`             | GET/POST/PUT/DELETE | Manage tasks                           |
| `/invitations/`       | POST                | Send invitations via email             |
| `/invitations/accept` | POST                | Accept invitation                      |

> Each endpoint requires JWT authentication where applicable.

---

## 🔹 Contributing

Contributions are welcome. Please follow these steps:

1. Fork the repository
2. Create a feature branch (`git checkout -b feature-name`)
3. Commit your changes (`git commit -m "Add new feature"`)
4. Push to the branch (`git push origin feature-name`)
5. Open a Pull Request

Ensure all code follows PEP8 standards and is well-documented.

## 🔹 License

This project is licensed under the **MIT License**.
See the [LICENSE](LICENSE) file for details.
