
CREATE TABLE budgets (
	month VARCHAR(7) NOT NULL, 
	charged NUMERIC(12, 6) NOT NULL, 
	video_seconds INTEGER NOT NULL, 
	PRIMARY KEY (month)
)

;

CREATE TABLE users (
	id VARCHAR(36) NOT NULL, 
	email VARCHAR(254) NOT NULL, 
	password_hash TEXT NOT NULL, 
	role VARCHAR(16) NOT NULL, 
	profile JSONB NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (email)
)

;

CREATE TABLE jobs (
	id VARCHAR(36) NOT NULL, 
	owner_id VARCHAR(36) NOT NULL, 
	kind VARCHAR(30) NOT NULL, 
	request_key VARCHAR(128) NOT NULL, 
	payload JSONB NOT NULL, 
	result JSONB NOT NULL, 
	checkpoints JSONB NOT NULL, 
	status VARCHAR(24) NOT NULL, 
	error TEXT, 
	attempts INTEGER NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	heartbeat TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (owner_id, request_key), 
	FOREIGN KEY(owner_id) REFERENCES users (id) ON DELETE CASCADE
)

;

CREATE TABLE records (
	id VARCHAR(36) NOT NULL, 
	owner_id VARCHAR(36), 
	kind VARCHAR(24) NOT NULL, 
	dedup_key VARCHAR(128), 
	status VARCHAR(24) NOT NULL, 
	data JSONB NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (owner_id, kind, dedup_key), 
	FOREIGN KEY(owner_id) REFERENCES users (id) ON DELETE CASCADE
)

;

CREATE TABLE sessions (
	token VARCHAR(64) NOT NULL, 
	user_id VARCHAR(36) NOT NULL, 
	csrf VARCHAR(64) NOT NULL, 
	expires TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (token), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
)

;

CREATE TABLE usage (
	key VARCHAR(160) NOT NULL, 
	month VARCHAR(7) NOT NULL, 
	operation VARCHAR(40) NOT NULL, 
	model VARCHAR(80) NOT NULL, 
	reserved NUMERIC(12, 6) NOT NULL, 
	actual NUMERIC(12, 6), 
	state VARCHAR(20) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (key), 
	FOREIGN KEY(month) REFERENCES budgets (month)
)

;

CREATE TABLE knowledge (
	record_id VARCHAR(36) NOT NULL, 
	text TEXT NOT NULL, 
	direction VARCHAR(20) NOT NULL, 
	level VARCHAR(10) NOT NULL, 
	language VARCHAR(2) NOT NULL, 
	embedding VECTOR(1536), 
	PRIMARY KEY (record_id), 
	FOREIGN KEY(record_id) REFERENCES records (id) ON DELETE CASCADE
)

;
CREATE INDEX ix_jobs_owner_id ON jobs (owner_id);
CREATE INDEX ix_jobs_status ON jobs (status);
CREATE INDEX ix_records_kind ON records (kind);
CREATE INDEX ix_records_owner_id ON records (owner_id);
CREATE INDEX ix_records_status ON records (status);
CREATE INDEX ix_sessions_user_id ON sessions (user_id);
