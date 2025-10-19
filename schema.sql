-- Run this in your PostgreSQL database first
CREATE TABLE IF NOT EXISTS groups (
    id SERIAL PRIMARY KEY,
    group_id BIGINT UNIQUE NOT NULL,
    group_name TEXT NOT NULL,
    group_type VARCHAR(20) NOT NULL,
    member_count INTEGER DEFAULT 0,
    status VARCHAR(20) DEFAULT 'safe',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_scan TIMESTAMP,
    is_active BOOLEAN DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS group_members (
    id SERIAL PRIMARY KEY,
    group_id BIGINT NOT NULL,
    user_id BIGINT NOT NULL,
    username TEXT,
    first_name TEXT,
    last_name TEXT,
    is_bot BOOLEAN DEFAULT FALSE,
    status VARCHAR(20) DEFAULT 'active',
    joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(group_id, user_id)
);

CREATE TABLE IF NOT EXISTS activities (
    id SERIAL PRIMARY KEY,
    group_id BIGINT NOT NULL,
    user_id BIGINT,
    activity_type VARCHAR(50) NOT NULL,
    content TEXT,
    risk_level VARCHAR(20) DEFAULT 'normal',
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS alerts (
    id SERIAL PRIMARY KEY,
    group_id BIGINT NOT NULL,
    alert_type VARCHAR(50) NOT NULL,
    alert_message TEXT NOT NULL,
    risk_level VARCHAR(20) NOT NULL,
    resolved BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS bot_settings (
    id SERIAL PRIMARY KEY,
    owner_id BIGINT NOT NULL UNIQUE,
    owner_username TEXT,
    alert_enabled BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create indexes for better performance
CREATE INDEX IF NOT EXISTS idx_groups_group_id ON groups(group_id);
CREATE INDEX IF NOT EXISTS idx_activities_group_id ON activities(group_id);
CREATE INDEX IF NOT EXISTS idx_activities_timestamp ON activities(timestamp);
CREATE INDEX IF NOT EXISTS idx_alerts_group_id ON alerts(group_id);
CREATE INDEX IF NOT EXISTS idx_alerts_created_at ON alerts(created_at);
CREATE INDEX IF NOT EXISTS idx_group_members_group_id ON group_members(group_id);
