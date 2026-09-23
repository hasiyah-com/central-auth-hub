-- baseline 609c11174142: schema หลัง baseline (เฉพาะโครงสร้าง)
-- ที่มา: create_all ของ models ที่ commit da0003b (commit ที่สร้าง baseline)
-- สร้างด้วย scripts/test/build_baseline_snapshot.sh — ห้ามแก้มือ

CREATE TABLE public.access_list (
    id uuid NOT NULL,
    subsystem_id uuid NOT NULL,
    user_id uuid NOT NULL,
    role_in_sub character varying(50),
    entry_type character varying(10) DEFAULT 'allow'::character varying NOT NULL,
    granted_by uuid,
    granted_at timestamp without time zone,
    revoked_at timestamp without time zone
);

CREATE TABLE public.api_alerts (
    id uuid NOT NULL,
    rule character varying(50) NOT NULL,
    severity character varying(20) NOT NULL,
    ip inet,
    user_id uuid,
    detail json,
    resolved boolean,
    created_at timestamp without time zone
);

CREATE TABLE public.app_settings (
    key character varying(100) NOT NULL,
    value json NOT NULL,
    updated_by uuid,
    updated_at timestamp without time zone
);

CREATE TABLE public.audit_logs (
    id uuid NOT NULL,
    actor_id uuid,
    action character varying(100) NOT NULL,
    target_type character varying(50),
    target_id uuid,
    ip inet,
    metadata json,
    created_at timestamp without time zone
);

CREATE TABLE public.ip_blacklist (
    id uuid NOT NULL,
    ip_address character varying(50) NOT NULL,
    reason text,
    added_by uuid,
    created_at timestamp without time zone
);

CREATE TABLE public.login_sessions (
    id uuid NOT NULL,
    user_id uuid,
    subsystem_id uuid,
    ip inet,
    user_agent text,
    geo_country character varying(50),
    geo_city character varying(100),
    os_name character varying(100),
    browser character varying(100),
    device_type character varying(20),
    anomaly_score numeric(3,2),
    risk_score numeric(4,3),
    risk_breakdown json,
    risk_reasons json,
    decision character varying(20),
    login_method character varying(20),
    is_attack_ip boolean,
    is_account_takeover boolean,
    created_at timestamp without time zone,
    logout_at timestamp without time zone,
    jti character varying(64)
);

CREATE TABLE public.ml_feedback (
    id uuid NOT NULL,
    session_id uuid NOT NULL,
    label character varying(20) NOT NULL,
    note text,
    marked_by uuid NOT NULL,
    created_at timestamp without time zone
);

CREATE TABLE public.passkey_backup_codes (
    id uuid NOT NULL,
    user_id uuid NOT NULL,
    code_hash text NOT NULL,
    used_at timestamp without time zone,
    used_ip inet,
    used_user_agent text,
    generation integer NOT NULL,
    created_at timestamp without time zone NOT NULL,
    acknowledged_at timestamp without time zone
);

CREATE TABLE public.passkey_credentials (
    id uuid NOT NULL,
    user_id uuid NOT NULL,
    credential_id bytea NOT NULL,
    public_key bytea NOT NULL,
    sign_count integer NOT NULL,
    aaguid uuid,
    transports character varying[] DEFAULT '{}'::character varying[] NOT NULL,
    device_name character varying(100) NOT NULL,
    device_type character varying(50),
    nickname_history jsonb DEFAULT '[]'::jsonb NOT NULL,
    created_at timestamp without time zone NOT NULL,
    last_used_at timestamp without time zone,
    last_used_ip inet,
    last_used_user_agent text,
    revoked_at timestamp without time zone,
    revoked_reason character varying(50),
    backup_eligible boolean,
    backup_state boolean,
    counter_regression_count integer NOT NULL,
    last_counter_regression_at timestamp without time zone
);

CREATE TABLE public.request_logs (
    id uuid NOT NULL,
    method character varying(10) NOT NULL,
    path text NOT NULL,
    status_code integer,
    user_id uuid,
    ip inet,
    user_agent text,
    duration_ms integer,
    error_detail text,
    created_at timestamp without time zone
);

CREATE TABLE public.secret_retrieval_tokens (
    id uuid NOT NULL,
    token character varying(128) NOT NULL,
    subsystem_id uuid NOT NULL,
    secret_encrypted text NOT NULL,
    expires_at timestamp without time zone NOT NULL,
    used_at timestamp without time zone,
    created_at timestamp without time zone
);

CREATE TABLE public.subsystem_change_requests (
    id uuid NOT NULL,
    subsystem_id uuid NOT NULL,
    requested_by uuid NOT NULL,
    request_type character varying(50) NOT NULL,
    payload json NOT NULL,
    status character varying(20) NOT NULL,
    reviewer_id uuid,
    reviewer_note text,
    created_at timestamp without time zone,
    reviewed_at timestamp without time zone
);

CREATE TABLE public.subsystems (
    id uuid NOT NULL,
    name character varying(255) NOT NULL,
    description text,
    client_id character varying(64) NOT NULL,
    client_secret_hash text NOT NULL,
    redirect_uris text[] NOT NULL,
    scope character varying[] NOT NULL,
    previous_client_secret_hash text,
    previous_secret_expires_at timestamp without time zone,
    allowed_roles character varying[] DEFAULT '{user}'::character varying[] NOT NULL,
    access_revoke_webhook_url text,
    status character varying(20),
    access_policy character varying(20) DEFAULT 'explicit'::character varying NOT NULL,
    access_policy_config json,
    api_key_hash text,
    api_key_prefix character varying(12),
    owner_user_id uuid,
    created_at timestamp without time zone,
    approved_at timestamp without time zone
);

CREATE TABLE public.users (
    id uuid NOT NULL,
    google_sub character varying(255),
    line_sub character varying,
    email character varying(255) NOT NULL,
    full_name character varying(255) NOT NULL,
    user_type character varying(20) NOT NULL,
    identifier character varying(50),
    faculty character varying(100),
    major character varying(100),
    year_or_position character varying(50),
    phone character varying(20),
    address text,
    status character varying(20),
    is_hub_admin boolean,
    email_verified boolean DEFAULT false NOT NULL,
    email_verified_at timestamp without time zone,
    created_at timestamp without time zone,
    updated_at timestamp without time zone
);

ALTER TABLE ONLY public.access_list
    ADD CONSTRAINT access_list_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.access_list
    ADD CONSTRAINT access_list_subsystem_id_user_id_key UNIQUE (subsystem_id, user_id);

ALTER TABLE ONLY public.api_alerts
    ADD CONSTRAINT api_alerts_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.app_settings
    ADD CONSTRAINT app_settings_pkey PRIMARY KEY (key);

ALTER TABLE ONLY public.audit_logs
    ADD CONSTRAINT audit_logs_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.ip_blacklist
    ADD CONSTRAINT ip_blacklist_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.login_sessions
    ADD CONSTRAINT login_sessions_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.ml_feedback
    ADD CONSTRAINT ml_feedback_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.passkey_backup_codes
    ADD CONSTRAINT passkey_backup_codes_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.passkey_credentials
    ADD CONSTRAINT passkey_credentials_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.request_logs
    ADD CONSTRAINT request_logs_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.secret_retrieval_tokens
    ADD CONSTRAINT secret_retrieval_tokens_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.subsystem_change_requests
    ADD CONSTRAINT subsystem_change_requests_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.subsystems
    ADD CONSTRAINT subsystems_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_pkey PRIMARY KEY (id);

CREATE INDEX ix_access_list_subsystem_id ON public.access_list USING btree (subsystem_id);

CREATE INDEX ix_access_list_user_id ON public.access_list USING btree (user_id);

CREATE INDEX ix_api_alerts_created_at ON public.api_alerts USING btree (created_at);

CREATE INDEX ix_api_alerts_ip ON public.api_alerts USING btree (ip);

CREATE INDEX ix_api_alerts_rule ON public.api_alerts USING btree (rule);

CREATE INDEX ix_api_alerts_user_id ON public.api_alerts USING btree (user_id);

CREATE INDEX ix_audit_logs_action ON public.audit_logs USING btree (action);

CREATE INDEX ix_audit_logs_created_at ON public.audit_logs USING btree (created_at);

CREATE UNIQUE INDEX ix_ip_blacklist_ip_address ON public.ip_blacklist USING btree (ip_address);

CREATE INDEX ix_login_sessions_created_at ON public.login_sessions USING btree (created_at);

CREATE INDEX ix_login_sessions_jti ON public.login_sessions USING btree (jti);

CREATE INDEX ix_login_sessions_login_method ON public.login_sessions USING btree (login_method);

CREATE INDEX ix_login_sessions_logout_at ON public.login_sessions USING btree (logout_at);

CREATE INDEX ix_login_sessions_subsystem_id ON public.login_sessions USING btree (subsystem_id);

CREATE INDEX ix_login_sessions_user_id ON public.login_sessions USING btree (user_id);

CREATE UNIQUE INDEX ix_ml_feedback_session_id ON public.ml_feedback USING btree (session_id);

CREATE INDEX ix_passkey_backup_codes_user_id ON public.passkey_backup_codes USING btree (user_id);

CREATE UNIQUE INDEX ix_passkey_credentials_credential_id ON public.passkey_credentials USING btree (credential_id);

CREATE INDEX ix_passkey_credentials_revoked_at ON public.passkey_credentials USING btree (revoked_at);

CREATE INDEX ix_passkey_credentials_user_id ON public.passkey_credentials USING btree (user_id);

CREATE INDEX ix_request_logs_created_at ON public.request_logs USING btree (created_at);

CREATE INDEX ix_request_logs_path ON public.request_logs USING btree (path);

CREATE INDEX ix_request_logs_status_code ON public.request_logs USING btree (status_code);

CREATE INDEX ix_request_logs_user_id ON public.request_logs USING btree (user_id);

CREATE UNIQUE INDEX ix_secret_retrieval_tokens_token ON public.secret_retrieval_tokens USING btree (token);

CREATE INDEX ix_subsystem_change_requests_created_at ON public.subsystem_change_requests USING btree (created_at);

CREATE INDEX ix_subsystem_change_requests_request_type ON public.subsystem_change_requests USING btree (request_type);

CREATE INDEX ix_subsystem_change_requests_requested_by ON public.subsystem_change_requests USING btree (requested_by);

CREATE INDEX ix_subsystem_change_requests_status ON public.subsystem_change_requests USING btree (status);

CREATE INDEX ix_subsystem_change_requests_subsystem_id ON public.subsystem_change_requests USING btree (subsystem_id);

CREATE UNIQUE INDEX ix_subsystems_client_id ON public.subsystems USING btree (client_id);

CREATE INDEX ix_subsystems_status ON public.subsystems USING btree (status);

CREATE UNIQUE INDEX ix_users_email ON public.users USING btree (email);

CREATE INDEX ix_users_faculty ON public.users USING btree (faculty);

CREATE UNIQUE INDEX ix_users_google_sub ON public.users USING btree (google_sub);

CREATE INDEX ix_users_identifier ON public.users USING btree (identifier);

CREATE INDEX ix_users_line_sub ON public.users USING btree (line_sub);

CREATE INDEX ix_users_status ON public.users USING btree (status);

CREATE INDEX ix_users_user_type ON public.users USING btree (user_type);

ALTER TABLE ONLY public.access_list
    ADD CONSTRAINT access_list_granted_by_fkey FOREIGN KEY (granted_by) REFERENCES public.users(id);

ALTER TABLE ONLY public.access_list
    ADD CONSTRAINT access_list_subsystem_id_fkey FOREIGN KEY (subsystem_id) REFERENCES public.subsystems(id);

ALTER TABLE ONLY public.access_list
    ADD CONSTRAINT access_list_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);

ALTER TABLE ONLY public.ip_blacklist
    ADD CONSTRAINT ip_blacklist_added_by_fkey FOREIGN KEY (added_by) REFERENCES public.users(id);

ALTER TABLE ONLY public.login_sessions
    ADD CONSTRAINT login_sessions_subsystem_id_fkey FOREIGN KEY (subsystem_id) REFERENCES public.subsystems(id);

ALTER TABLE ONLY public.login_sessions
    ADD CONSTRAINT login_sessions_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);

ALTER TABLE ONLY public.ml_feedback
    ADD CONSTRAINT ml_feedback_marked_by_fkey FOREIGN KEY (marked_by) REFERENCES public.users(id);

ALTER TABLE ONLY public.ml_feedback
    ADD CONSTRAINT ml_feedback_session_id_fkey FOREIGN KEY (session_id) REFERENCES public.login_sessions(id);

ALTER TABLE ONLY public.passkey_backup_codes
    ADD CONSTRAINT passkey_backup_codes_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.passkey_credentials
    ADD CONSTRAINT passkey_credentials_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.secret_retrieval_tokens
    ADD CONSTRAINT secret_retrieval_tokens_subsystem_id_fkey FOREIGN KEY (subsystem_id) REFERENCES public.subsystems(id);

ALTER TABLE ONLY public.subsystem_change_requests
    ADD CONSTRAINT subsystem_change_requests_requested_by_fkey FOREIGN KEY (requested_by) REFERENCES public.users(id);

ALTER TABLE ONLY public.subsystem_change_requests
    ADD CONSTRAINT subsystem_change_requests_reviewer_id_fkey FOREIGN KEY (reviewer_id) REFERENCES public.users(id);

ALTER TABLE ONLY public.subsystem_change_requests
    ADD CONSTRAINT subsystem_change_requests_subsystem_id_fkey FOREIGN KEY (subsystem_id) REFERENCES public.subsystems(id);

ALTER TABLE ONLY public.subsystems
    ADD CONSTRAINT subsystems_owner_user_id_fkey FOREIGN KEY (owner_user_id) REFERENCES public.users(id);
