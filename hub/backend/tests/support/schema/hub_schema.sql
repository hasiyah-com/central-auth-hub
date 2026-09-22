-- schema snapshot ของฐานข้อมูลเทส (เฉพาะโครงสร้าง ไม่มีข้อมูล)
-- alembic head: a7b8c9d0e1f2
-- สร้างด้วย scripts/test/dump_test_schema.sh จาก hub_db
--
-- PostgreSQL database dump
--

\restrict vsYrdT1YKoHOFlwsgak6Pso2xTHppU9X4akb07Lg70kmXadG4JGs4fNcHthTVgR

-- Dumped from database version 15.17
-- Dumped by pg_dump version 15.17

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: expert_review_forbid_update(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.expert_review_forbid_update() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
        BEGIN
          RAISE EXCEPTION USING
            MESSAGE = 'append-only table ' || TG_TABLE_NAME
                      || ': UPDATE is not allowed, insert a new row instead';
        END;
        $$;


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: access_list; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.access_list (
    id uuid NOT NULL,
    subsystem_id uuid NOT NULL,
    user_id uuid NOT NULL,
    role_in_sub character varying(50),
    granted_by uuid,
    granted_at timestamp without time zone,
    revoked_at timestamp without time zone,
    entry_type character varying(10) DEFAULT 'allow'::character varying NOT NULL
);


--
-- Name: api_alerts; Type: TABLE; Schema: public; Owner: -
--

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


--
-- Name: app_settings; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.app_settings (
    key character varying(100) NOT NULL,
    value json NOT NULL,
    updated_by uuid,
    updated_at timestamp without time zone
);


--
-- Name: audit_logs; Type: TABLE; Schema: public; Owner: -
--

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


--
-- Name: expert_alert_groups; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.expert_alert_groups (
    id uuid NOT NULL,
    group_key character varying(255) NOT NULL,
    user_id uuid,
    primary_signal character varying(120) NOT NULL,
    window_start timestamp without time zone NOT NULL,
    session_ids json NOT NULL,
    n_events integer NOT NULL,
    first_seen_at timestamp without time zone NOT NULL,
    last_seen_at timestamp without time zone NOT NULL,
    shadow_epoch_id character varying(64),
    risk_config_id character varying(64),
    calibration_version character varying(64),
    calibration_sha256 character varying(64),
    scoring_commit character varying(64),
    provenance character varying(10) NOT NULL,
    eligible_for_production_metrics boolean DEFAULT false NOT NULL,
    double_review boolean DEFAULT false NOT NULL,
    created_at timestamp without time zone DEFAULT timezone('utc'::text, now()) NOT NULL,
    CONSTRAINT ck_expert_alert_groups_eligible CHECK (((NOT eligible_for_production_metrics) OR (((provenance)::text = 'external'::text) AND (risk_config_id IS NOT NULL) AND (scoring_commit IS NOT NULL)))),
    CONSTRAINT ck_expert_alert_groups_provenance CHECK (((provenance)::text = ANY ((ARRAY['demo'::character varying, 'test'::character varying, 'unknown'::character varying, 'local'::character varying, 'external'::character varying])::text[])))
);


--
-- Name: expert_reviews; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.expert_reviews (
    id uuid NOT NULL,
    group_id uuid NOT NULL,
    reviewer_id uuid NOT NULL,
    round smallint NOT NULL,
    model_output_visible boolean NOT NULL,
    verdict character varying(24) NOT NULL,
    confidence character varying(8) NOT NULL,
    reason_codes json NOT NULL,
    comment text,
    time_spent_sec integer,
    supersedes_id uuid,
    created_at timestamp without time zone DEFAULT timezone('utc'::text, now()) NOT NULL,
    CONSTRAINT ck_expert_reviews_confidence CHECK (((confidence)::text = ANY ((ARRAY['low'::character varying, 'medium'::character varying, 'high'::character varying])::text[]))),
    CONSTRAINT ck_expert_reviews_round_visibility CHECK ((((round = 1) AND (model_output_visible = false)) OR ((round = 2) AND (model_output_visible = true)))),
    CONSTRAINT ck_expert_reviews_verdict CHECK (((verdict)::text = ANY ((ARRAY['benign'::character varying, 'suspicious'::character varying, 'confirmed_attack'::character varying, 'insufficient_context'::character varying])::text[])))
);


--
-- Name: ip_blacklist; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ip_blacklist (
    id uuid NOT NULL,
    ip_address character varying(50) NOT NULL,
    reason text,
    added_by uuid,
    created_at timestamp without time zone
);


--
-- Name: login_sessions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.login_sessions (
    id uuid NOT NULL,
    user_id uuid,
    subsystem_id uuid,
    ip inet,
    user_agent text,
    geo_country character varying(50),
    geo_city character varying(100),
    anomaly_score numeric(3,2),
    decision character varying(20),
    created_at timestamp without time zone,
    os_name character varying(100),
    browser character varying(100),
    device_type character varying(20),
    is_attack_ip boolean DEFAULT false,
    is_account_takeover boolean DEFAULT false,
    risk_score numeric(4,3),
    risk_breakdown json,
    risk_reasons json,
    logout_at timestamp without time zone,
    jti character varying(64),
    login_method character varying(20),
    refresh_id character varying(64),
    last_seen_at timestamp without time zone,
    actual_decision_source character varying(32),
    baseline_shadow_score numeric(4,3),
    baseline_shadow_decision character varying(20),
    hybrid_shadow_score numeric(4,3),
    hybrid_shadow_decision character varying(20),
    l3_changed_shadow_decision boolean,
    l3_eligibility character varying(20),
    l3_n_history integer,
    calibrated boolean,
    calibration_version character varying(64),
    calibration_sha256 character varying(64),
    risk_config_id character varying(64),
    shadow_epoch_id character varying(64),
    scoring_commit character varying(64),
    latency_total_ms integer,
    latency_l3_ms integer
);


--
-- Name: ml_feedback; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ml_feedback (
    id uuid NOT NULL,
    session_id uuid NOT NULL,
    label character varying(20) NOT NULL,
    note text,
    marked_by uuid NOT NULL,
    created_at timestamp without time zone
);


--
-- Name: passkey_backup_codes; Type: TABLE; Schema: public; Owner: -
--

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


--
-- Name: passkey_credentials; Type: TABLE; Schema: public; Owner: -
--

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
    last_counter_regression_at timestamp without time zone,
    status character varying(20) DEFAULT 'ACTIVE'::character varying NOT NULL
);


--
-- Name: recovery_ticket_approvals; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.recovery_ticket_approvals (
    id uuid NOT NULL,
    ticket_id uuid NOT NULL,
    admin_id uuid NOT NULL,
    evidence_type character varying(30),
    evidence_note text,
    remark text,
    approved_at timestamp without time zone NOT NULL
);


--
-- Name: recovery_tickets; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.recovery_tickets (
    id uuid NOT NULL,
    user_id uuid,
    email character varying(255) NOT NULL,
    credential_type character varying(20),
    reason text,
    recovery_level character varying(10) DEFAULT 'NORMAL'::character varying NOT NULL,
    status character varying(20) DEFAULT 'pending'::character varying NOT NULL,
    requested_ip inet,
    link_token text,
    token_expires_at timestamp without time zone,
    consumed_at timestamp without time zone,
    created_at timestamp without time zone NOT NULL
);


--
-- Name: request_logs; Type: TABLE; Schema: public; Owner: -
--

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


--
-- Name: secret_retrieval_tokens; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.secret_retrieval_tokens (
    id uuid NOT NULL,
    token character varying(128) NOT NULL,
    subsystem_id uuid NOT NULL,
    secret_encrypted text NOT NULL,
    expires_at timestamp without time zone NOT NULL,
    used_at timestamp without time zone,
    created_at timestamp without time zone
);


--
-- Name: subsystem_change_requests; Type: TABLE; Schema: public; Owner: -
--

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


--
-- Name: subsystems; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.subsystems (
    id uuid NOT NULL,
    name character varying(255) NOT NULL,
    description text,
    client_id character varying(64) NOT NULL,
    client_secret_hash text NOT NULL,
    redirect_uris text[] NOT NULL,
    scope character varying[] NOT NULL,
    status character varying(20),
    owner_user_id uuid,
    created_at timestamp without time zone,
    approved_at timestamp without time zone,
    allowed_roles character varying[] DEFAULT '{user}'::character varying[] NOT NULL,
    access_revoke_webhook_url text,
    previous_client_secret_hash text,
    previous_secret_expires_at timestamp without time zone,
    access_policy character varying(20) DEFAULT 'explicit'::character varying NOT NULL,
    access_policy_config json,
    api_key_hash text,
    api_key_prefix character varying(12)
);


--
-- Name: system_dispositions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.system_dispositions (
    id uuid NOT NULL,
    group_id uuid NOT NULL,
    disposition character varying(20) NOT NULL,
    decision_counts json NOT NULL,
    max_risk_score numeric(4,3),
    primary_layer character varying(20),
    model_output json NOT NULL,
    created_at timestamp without time zone DEFAULT timezone('utc'::text, now()) NOT NULL
);


--
-- Name: user_totp_credentials; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.user_totp_credentials (
    id uuid NOT NULL,
    user_id uuid NOT NULL,
    secret_encrypted text NOT NULL,
    status character varying(20) DEFAULT 'REGISTERED'::character varying NOT NULL,
    created_at timestamp without time zone NOT NULL,
    enabled_at timestamp without time zone,
    last_used_at timestamp without time zone
);


--
-- Name: users; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.users (
    id uuid NOT NULL,
    google_sub character varying(255),
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
    created_at timestamp without time zone,
    updated_at timestamp without time zone,
    line_sub character varying,
    email_verified boolean DEFAULT false NOT NULL,
    email_verified_at timestamp without time zone,
    mfa_always boolean DEFAULT false NOT NULL,
    mfa_preferred_factor character varying(16),
    security_onboarding_dismissed boolean DEFAULT false NOT NULL,
    security_onboarding_snoozed_until timestamp without time zone
);


--
-- Name: access_list access_list_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.access_list
    ADD CONSTRAINT access_list_pkey PRIMARY KEY (id);


--
-- Name: access_list access_list_subsystem_id_user_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.access_list
    ADD CONSTRAINT access_list_subsystem_id_user_id_key UNIQUE (subsystem_id, user_id);


--
-- Name: api_alerts api_alerts_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.api_alerts
    ADD CONSTRAINT api_alerts_pkey PRIMARY KEY (id);


--
-- Name: app_settings app_settings_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.app_settings
    ADD CONSTRAINT app_settings_pkey PRIMARY KEY (key);


--
-- Name: audit_logs audit_logs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_logs
    ADD CONSTRAINT audit_logs_pkey PRIMARY KEY (id);


--
-- Name: expert_alert_groups expert_alert_groups_group_key_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.expert_alert_groups
    ADD CONSTRAINT expert_alert_groups_group_key_key UNIQUE (group_key);


--
-- Name: expert_alert_groups expert_alert_groups_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.expert_alert_groups
    ADD CONSTRAINT expert_alert_groups_pkey PRIMARY KEY (id);


--
-- Name: expert_reviews expert_reviews_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.expert_reviews
    ADD CONSTRAINT expert_reviews_pkey PRIMARY KEY (id);


--
-- Name: expert_reviews expert_reviews_supersedes_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.expert_reviews
    ADD CONSTRAINT expert_reviews_supersedes_id_key UNIQUE (supersedes_id);


--
-- Name: ip_blacklist ip_blacklist_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ip_blacklist
    ADD CONSTRAINT ip_blacklist_pkey PRIMARY KEY (id);


--
-- Name: login_sessions login_sessions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.login_sessions
    ADD CONSTRAINT login_sessions_pkey PRIMARY KEY (id);


--
-- Name: ml_feedback ml_feedback_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ml_feedback
    ADD CONSTRAINT ml_feedback_pkey PRIMARY KEY (id);


--
-- Name: passkey_backup_codes passkey_backup_codes_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.passkey_backup_codes
    ADD CONSTRAINT passkey_backup_codes_pkey PRIMARY KEY (id);


--
-- Name: passkey_credentials passkey_credentials_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.passkey_credentials
    ADD CONSTRAINT passkey_credentials_pkey PRIMARY KEY (id);


--
-- Name: recovery_ticket_approvals recovery_ticket_approvals_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.recovery_ticket_approvals
    ADD CONSTRAINT recovery_ticket_approvals_pkey PRIMARY KEY (id);


--
-- Name: recovery_ticket_approvals recovery_ticket_approvals_ticket_id_admin_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.recovery_ticket_approvals
    ADD CONSTRAINT recovery_ticket_approvals_ticket_id_admin_id_key UNIQUE (ticket_id, admin_id);


--
-- Name: recovery_tickets recovery_tickets_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.recovery_tickets
    ADD CONSTRAINT recovery_tickets_pkey PRIMARY KEY (id);


--
-- Name: request_logs request_logs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.request_logs
    ADD CONSTRAINT request_logs_pkey PRIMARY KEY (id);


--
-- Name: secret_retrieval_tokens secret_retrieval_tokens_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.secret_retrieval_tokens
    ADD CONSTRAINT secret_retrieval_tokens_pkey PRIMARY KEY (id);


--
-- Name: subsystem_change_requests subsystem_change_requests_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.subsystem_change_requests
    ADD CONSTRAINT subsystem_change_requests_pkey PRIMARY KEY (id);


--
-- Name: subsystems subsystems_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.subsystems
    ADD CONSTRAINT subsystems_pkey PRIMARY KEY (id);


--
-- Name: system_dispositions system_dispositions_group_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.system_dispositions
    ADD CONSTRAINT system_dispositions_group_id_key UNIQUE (group_id);


--
-- Name: system_dispositions system_dispositions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.system_dispositions
    ADD CONSTRAINT system_dispositions_pkey PRIMARY KEY (id);


--
-- Name: expert_reviews uq_expert_reviews_chain_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.expert_reviews
    ADD CONSTRAINT uq_expert_reviews_chain_key UNIQUE (id, group_id, reviewer_id, round);


--
-- Name: user_totp_credentials user_totp_credentials_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_totp_credentials
    ADD CONSTRAINT user_totp_credentials_pkey PRIMARY KEY (id);


--
-- Name: user_totp_credentials user_totp_credentials_user_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_totp_credentials
    ADD CONSTRAINT user_totp_credentials_user_id_key UNIQUE (user_id);


--
-- Name: users users_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_pkey PRIMARY KEY (id);


--
-- Name: ix_access_list_subsystem_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_access_list_subsystem_id ON public.access_list USING btree (subsystem_id);


--
-- Name: ix_access_list_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_access_list_user_id ON public.access_list USING btree (user_id);


--
-- Name: ix_api_alerts_created_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_api_alerts_created_at ON public.api_alerts USING btree (created_at);


--
-- Name: ix_api_alerts_ip; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_api_alerts_ip ON public.api_alerts USING btree (ip);


--
-- Name: ix_api_alerts_rule; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_api_alerts_rule ON public.api_alerts USING btree (rule);


--
-- Name: ix_api_alerts_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_api_alerts_user_id ON public.api_alerts USING btree (user_id);


--
-- Name: ix_audit_logs_action; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_audit_logs_action ON public.audit_logs USING btree (action);


--
-- Name: ix_audit_logs_created_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_audit_logs_created_at ON public.audit_logs USING btree (created_at);


--
-- Name: ix_expert_alert_groups_provenance; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_expert_alert_groups_provenance ON public.expert_alert_groups USING btree (provenance);


--
-- Name: ix_expert_alert_groups_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_expert_alert_groups_user_id ON public.expert_alert_groups USING btree (user_id);


--
-- Name: ix_expert_alert_groups_window_start; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_expert_alert_groups_window_start ON public.expert_alert_groups USING btree (window_start);


--
-- Name: ix_expert_reviews_group_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_expert_reviews_group_id ON public.expert_reviews USING btree (group_id);


--
-- Name: ix_expert_reviews_reviewer_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_expert_reviews_reviewer_id ON public.expert_reviews USING btree (reviewer_id);


--
-- Name: ix_ip_blacklist_ip_address; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_ip_blacklist_ip_address ON public.ip_blacklist USING btree (ip_address);


--
-- Name: ix_login_sessions_created_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_login_sessions_created_at ON public.login_sessions USING btree (created_at);


--
-- Name: ix_login_sessions_jti; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_login_sessions_jti ON public.login_sessions USING btree (jti);


--
-- Name: ix_login_sessions_l3_changed_shadow_decision; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_login_sessions_l3_changed_shadow_decision ON public.login_sessions USING btree (l3_changed_shadow_decision);


--
-- Name: ix_login_sessions_last_seen_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_login_sessions_last_seen_at ON public.login_sessions USING btree (last_seen_at);


--
-- Name: ix_login_sessions_login_method; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_login_sessions_login_method ON public.login_sessions USING btree (login_method);


--
-- Name: ix_login_sessions_logout_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_login_sessions_logout_at ON public.login_sessions USING btree (logout_at);


--
-- Name: ix_login_sessions_refresh_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_login_sessions_refresh_id ON public.login_sessions USING btree (refresh_id);


--
-- Name: ix_login_sessions_shadow_epoch_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_login_sessions_shadow_epoch_id ON public.login_sessions USING btree (shadow_epoch_id);


--
-- Name: ix_login_sessions_subsystem_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_login_sessions_subsystem_id ON public.login_sessions USING btree (subsystem_id);


--
-- Name: ix_login_sessions_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_login_sessions_user_id ON public.login_sessions USING btree (user_id);


--
-- Name: ix_ml_feedback_session_id; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_ml_feedback_session_id ON public.ml_feedback USING btree (session_id);


--
-- Name: ix_passkey_backup_codes_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_passkey_backup_codes_user_id ON public.passkey_backup_codes USING btree (user_id);


--
-- Name: ix_passkey_credentials_credential_id; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_passkey_credentials_credential_id ON public.passkey_credentials USING btree (credential_id);


--
-- Name: ix_passkey_credentials_revoked_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_passkey_credentials_revoked_at ON public.passkey_credentials USING btree (revoked_at);


--
-- Name: ix_passkey_credentials_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_passkey_credentials_status ON public.passkey_credentials USING btree (status);


--
-- Name: ix_passkey_credentials_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_passkey_credentials_user_id ON public.passkey_credentials USING btree (user_id);


--
-- Name: ix_recovery_ticket_approvals_ticket_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_recovery_ticket_approvals_ticket_id ON public.recovery_ticket_approvals USING btree (ticket_id);


--
-- Name: ix_recovery_tickets_email; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_recovery_tickets_email ON public.recovery_tickets USING btree (email);


--
-- Name: ix_recovery_tickets_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_recovery_tickets_status ON public.recovery_tickets USING btree (status);


--
-- Name: ix_recovery_tickets_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_recovery_tickets_user_id ON public.recovery_tickets USING btree (user_id);


--
-- Name: ix_request_logs_created_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_request_logs_created_at ON public.request_logs USING btree (created_at);


--
-- Name: ix_request_logs_path; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_request_logs_path ON public.request_logs USING btree (path);


--
-- Name: ix_request_logs_status_code; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_request_logs_status_code ON public.request_logs USING btree (status_code);


--
-- Name: ix_request_logs_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_request_logs_user_id ON public.request_logs USING btree (user_id);


--
-- Name: ix_secret_retrieval_tokens_token; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_secret_retrieval_tokens_token ON public.secret_retrieval_tokens USING btree (token);


--
-- Name: ix_subsystem_change_requests_created_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_subsystem_change_requests_created_at ON public.subsystem_change_requests USING btree (created_at);


--
-- Name: ix_subsystem_change_requests_request_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_subsystem_change_requests_request_type ON public.subsystem_change_requests USING btree (request_type);


--
-- Name: ix_subsystem_change_requests_requested_by; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_subsystem_change_requests_requested_by ON public.subsystem_change_requests USING btree (requested_by);


--
-- Name: ix_subsystem_change_requests_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_subsystem_change_requests_status ON public.subsystem_change_requests USING btree (status);


--
-- Name: ix_subsystem_change_requests_subsystem_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_subsystem_change_requests_subsystem_id ON public.subsystem_change_requests USING btree (subsystem_id);


--
-- Name: ix_subsystems_client_id; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_subsystems_client_id ON public.subsystems USING btree (client_id);


--
-- Name: ix_subsystems_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_subsystems_status ON public.subsystems USING btree (status);


--
-- Name: ix_user_totp_credentials_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_user_totp_credentials_status ON public.user_totp_credentials USING btree (status);


--
-- Name: ix_user_totp_credentials_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_user_totp_credentials_user_id ON public.user_totp_credentials USING btree (user_id);


--
-- Name: ix_users_email; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_users_email ON public.users USING btree (email);


--
-- Name: ix_users_faculty; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_users_faculty ON public.users USING btree (faculty);


--
-- Name: ix_users_google_sub; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_users_google_sub ON public.users USING btree (google_sub);


--
-- Name: ix_users_identifier; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_users_identifier ON public.users USING btree (identifier);


--
-- Name: ix_users_line_sub; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_users_line_sub ON public.users USING btree (line_sub);


--
-- Name: ix_users_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_users_status ON public.users USING btree (status);


--
-- Name: ix_users_user_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_users_user_type ON public.users USING btree (user_type);


--
-- Name: uq_expert_reviews_one_root; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_expert_reviews_one_root ON public.expert_reviews USING btree (group_id, reviewer_id, round) WHERE (supersedes_id IS NULL);


--
-- Name: expert_reviews expert_reviews_no_update; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER expert_reviews_no_update BEFORE UPDATE ON public.expert_reviews FOR EACH ROW EXECUTE FUNCTION public.expert_review_forbid_update();


--
-- Name: system_dispositions system_dispositions_no_update; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER system_dispositions_no_update BEFORE UPDATE ON public.system_dispositions FOR EACH ROW EXECUTE FUNCTION public.expert_review_forbid_update();


--
-- Name: access_list access_list_granted_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.access_list
    ADD CONSTRAINT access_list_granted_by_fkey FOREIGN KEY (granted_by) REFERENCES public.users(id);


--
-- Name: access_list access_list_subsystem_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.access_list
    ADD CONSTRAINT access_list_subsystem_id_fkey FOREIGN KEY (subsystem_id) REFERENCES public.subsystems(id);


--
-- Name: access_list access_list_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.access_list
    ADD CONSTRAINT access_list_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);


--
-- Name: expert_alert_groups expert_alert_groups_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.expert_alert_groups
    ADD CONSTRAINT expert_alert_groups_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);


--
-- Name: expert_reviews expert_reviews_group_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.expert_reviews
    ADD CONSTRAINT expert_reviews_group_id_fkey FOREIGN KEY (group_id) REFERENCES public.expert_alert_groups(id);


--
-- Name: expert_reviews expert_reviews_reviewer_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.expert_reviews
    ADD CONSTRAINT expert_reviews_reviewer_id_fkey FOREIGN KEY (reviewer_id) REFERENCES public.users(id);


--
-- Name: expert_reviews expert_reviews_supersedes_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.expert_reviews
    ADD CONSTRAINT expert_reviews_supersedes_id_fkey FOREIGN KEY (supersedes_id) REFERENCES public.expert_reviews(id);


--
-- Name: expert_reviews fk_expert_reviews_supersedes_same_chain; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.expert_reviews
    ADD CONSTRAINT fk_expert_reviews_supersedes_same_chain FOREIGN KEY (supersedes_id, group_id, reviewer_id, round) REFERENCES public.expert_reviews(id, group_id, reviewer_id, round);


--
-- Name: ip_blacklist ip_blacklist_added_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ip_blacklist
    ADD CONSTRAINT ip_blacklist_added_by_fkey FOREIGN KEY (added_by) REFERENCES public.users(id);


--
-- Name: login_sessions login_sessions_subsystem_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.login_sessions
    ADD CONSTRAINT login_sessions_subsystem_id_fkey FOREIGN KEY (subsystem_id) REFERENCES public.subsystems(id);


--
-- Name: login_sessions login_sessions_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.login_sessions
    ADD CONSTRAINT login_sessions_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);


--
-- Name: ml_feedback ml_feedback_marked_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ml_feedback
    ADD CONSTRAINT ml_feedback_marked_by_fkey FOREIGN KEY (marked_by) REFERENCES public.users(id);


--
-- Name: ml_feedback ml_feedback_session_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ml_feedback
    ADD CONSTRAINT ml_feedback_session_id_fkey FOREIGN KEY (session_id) REFERENCES public.login_sessions(id);


--
-- Name: passkey_backup_codes passkey_backup_codes_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.passkey_backup_codes
    ADD CONSTRAINT passkey_backup_codes_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: passkey_credentials passkey_credentials_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.passkey_credentials
    ADD CONSTRAINT passkey_credentials_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: recovery_ticket_approvals recovery_ticket_approvals_admin_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.recovery_ticket_approvals
    ADD CONSTRAINT recovery_ticket_approvals_admin_id_fkey FOREIGN KEY (admin_id) REFERENCES public.users(id);


--
-- Name: recovery_ticket_approvals recovery_ticket_approvals_ticket_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.recovery_ticket_approvals
    ADD CONSTRAINT recovery_ticket_approvals_ticket_id_fkey FOREIGN KEY (ticket_id) REFERENCES public.recovery_tickets(id) ON DELETE CASCADE;


--
-- Name: recovery_tickets recovery_tickets_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.recovery_tickets
    ADD CONSTRAINT recovery_tickets_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);


--
-- Name: secret_retrieval_tokens secret_retrieval_tokens_subsystem_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.secret_retrieval_tokens
    ADD CONSTRAINT secret_retrieval_tokens_subsystem_id_fkey FOREIGN KEY (subsystem_id) REFERENCES public.subsystems(id);


--
-- Name: subsystem_change_requests subsystem_change_requests_requested_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.subsystem_change_requests
    ADD CONSTRAINT subsystem_change_requests_requested_by_fkey FOREIGN KEY (requested_by) REFERENCES public.users(id);


--
-- Name: subsystem_change_requests subsystem_change_requests_reviewer_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.subsystem_change_requests
    ADD CONSTRAINT subsystem_change_requests_reviewer_id_fkey FOREIGN KEY (reviewer_id) REFERENCES public.users(id);


--
-- Name: subsystem_change_requests subsystem_change_requests_subsystem_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.subsystem_change_requests
    ADD CONSTRAINT subsystem_change_requests_subsystem_id_fkey FOREIGN KEY (subsystem_id) REFERENCES public.subsystems(id);


--
-- Name: subsystems subsystems_owner_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.subsystems
    ADD CONSTRAINT subsystems_owner_user_id_fkey FOREIGN KEY (owner_user_id) REFERENCES public.users(id);


--
-- Name: system_dispositions system_dispositions_group_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.system_dispositions
    ADD CONSTRAINT system_dispositions_group_id_fkey FOREIGN KEY (group_id) REFERENCES public.expert_alert_groups(id);


--
-- Name: user_totp_credentials user_totp_credentials_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_totp_credentials
    ADD CONSTRAINT user_totp_credentials_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- PostgreSQL database dump complete
--

\unrestrict vsYrdT1YKoHOFlwsgak6Pso2xTHppU9X4akb07Lg70kmXadG4JGs4fNcHthTVgR
