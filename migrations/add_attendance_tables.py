# migrations/add_attendance_tables.py
from sqlmodel import SQLModel, create_engine, text
from core.database import SQLALCHEMY_DATABASE_URL

def add_attendance_tables():
    """Migration script to add attendance tables"""
    engine = create_engine(SQLALCHEMY_DATABASE_URL)
    
    # Create tables
    SQLModel.metadata.create_all(engine)
    
    # Add specific table creation SQL for new tables
    with engine.connect() as conn:
        # Create attendance table
        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS attendance (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES "user"(id) ON DELETE CASCADE,
            organization_id INTEGER NOT NULL REFERENCES organization(id) ON DELETE CASCADE,
            date DATE NOT NULL,
            check_in TIME,
            check_out TIME,
            total_hours VARCHAR(10),
            overtime VARCHAR(10),
            location VARCHAR(50),
            status VARCHAR(20) NOT NULL DEFAULT 'present',
            is_late BOOLEAN DEFAULT FALSE,
            breaks_data JSONB,
            latitude FLOAT,
            longitude FLOAT,
            address TEXT,
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT unique_user_date UNIQUE(user_id, date)
        );
        """))
        
        # Create indexes
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_attendance_user_id ON attendance(user_id);"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_attendance_date ON attendance(date);"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_attendance_status ON attendance(status);"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_attendance_org ON attendance(organization_id);"))
        
        # Create active_session table
        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS active_session (
            id SERIAL PRIMARY KEY,
            user_id INTEGER UNIQUE NOT NULL REFERENCES "user"(id) ON DELETE CASCADE,
            organization_id INTEGER NOT NULL REFERENCES organization(id) ON DELETE CASCADE,
            is_checked_in BOOLEAN DEFAULT FALSE,
            check_in_time TIMESTAMP,
            check_out_time TIMESTAMP,
            check_in_location VARCHAR(50),
            is_on_break BOOLEAN DEFAULT FALSE,
            break_start_time TIMESTAMP,
            break_type VARCHAR(20),
            break_notes TEXT,
            latitude FLOAT,
            longitude FLOAT,
            address TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """))
        
        # Create break_history table
        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS break_history (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES "user"(id) ON DELETE CASCADE,
            organization_id INTEGER NOT NULL REFERENCES organization(id) ON DELETE CASCADE,
            attendance_id INTEGER REFERENCES attendance(id) ON DELETE CASCADE,
            break_type VARCHAR(20) NOT NULL,
            start_time TIMESTAMP NOT NULL,
            end_time TIMESTAMP,
            duration VARCHAR(10),
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """))
        
        conn.commit()
    
    print("Attendance tables created successfully!")

if __name__ == "__main__":
    add_attendance_tables()