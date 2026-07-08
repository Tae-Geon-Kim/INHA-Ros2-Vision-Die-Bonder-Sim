CREATE_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS "user" (
    index SERIAL PRIMARY KEY,
    id VARCHAR(50) UNIQUE NOT NULL,
    password TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS work_history (
    history_id SERIAL PRIMARY KEY,
    die_serial_number VARCHAR(100) NOT NULL,
    start_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    end_time TIMESTAMP,
    status VARCHAR(20) DEFAULT 'START'
);

CREATE TABLE IF NOT EXISTS user_logs (
    log_id BIGSERIAL PRIMARY KEY,
    user_index INT REFERENCES "user"(index) ON DELETE CASCADE,
    action_type VARCHAR(50) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS robot_error_logs (
    log_id SERIAL PRIMARY KEY,
    error_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    error_level VARCHAR(20) NOT NULL, -- WARN, FATAL
    error_code VARCHAR(50),
    detail TEXT,
    history_id INT REFERENCES work_history(history_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS vision_align_logs (
    align_id SERIAL PRIMARY KEY,
    history_id INT REFERENCES work_history(history_id) ON DELETE CASCADE,
    process_step VARCHAR(20) NOT NULL, -- PICK, PLACE
    camera_type VARCHAR(50) NOT NULL, -- MACRO, MICRO_TL 등
    offset_x FLOAT DEFAULT 0.0,
    offset_y FLOAT DEFAULT 0.0,
    offset_theta FLOAT DEFAULT 0.0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""