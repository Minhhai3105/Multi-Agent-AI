-- Multi-Agent AI Platform - PostgreSQL schema (11 tables)
-- Generated with pg_dump --schema-only from the running application database.
-- The backend creates this schema automatically at startup; this file is for review/DBeaver.

\restrict YeeOgJsucJxFT7q2nyfbCRQrOyHICHwrWZZttihacOSr4forrjarRyANx8B2rcQ
CREATE TABLE public.activity_logs (
    id bigint NOT NULL,
    user_id bigint,
    action character varying(100) NOT NULL,
    entity_type character varying(50) NOT NULL,
    entity_id bigint,
    message text NOT NULL,
    detail_json jsonb NOT NULL,
    created_at timestamp with time zone NOT NULL
);
CREATE SEQUENCE public.activity_logs_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
ALTER SEQUENCE public.activity_logs_id_seq OWNED BY public.activity_logs.id;
CREATE TABLE public.agents (
    id bigint NOT NULL,
    name character varying(150) NOT NULL,
    role_name character varying(150) NOT NULL,
    instruction text NOT NULL,
    model_name character varying(100) NOT NULL,
    temperature double precision NOT NULL,
    knowledge_collection character varying(100),
    is_active boolean NOT NULL,
    created_by bigint,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_agents_temperature CHECK (((temperature >= (0)::double precision) AND (temperature <= (2)::double precision)))
);
CREATE SEQUENCE public.agents_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
ALTER SEQUENCE public.agents_id_seq OWNED BY public.agents.id;
CREATE TABLE public.knowledge_chunks (
    id bigint NOT NULL,
    document_id bigint NOT NULL,
    chunk_index integer NOT NULL,
    heading character varying(255) NOT NULL,
    content text NOT NULL
);
CREATE SEQUENCE public.knowledge_chunks_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
ALTER SEQUENCE public.knowledge_chunks_id_seq OWNED BY public.knowledge_chunks.id;
CREATE TABLE public.knowledge_documents (
    id bigint NOT NULL,
    collection character varying(100) NOT NULL,
    title character varying(255) NOT NULL,
    filename character varying(255) NOT NULL,
    content_type character varying(100) NOT NULL,
    char_count integer NOT NULL,
    chunk_count integer NOT NULL,
    is_active boolean NOT NULL,
    uploaded_by bigint,
    created_at timestamp with time zone NOT NULL
);
CREATE SEQUENCE public.knowledge_documents_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
ALTER SEQUENCE public.knowledge_documents_id_seq OWNED BY public.knowledge_documents.id;
CREATE TABLE public.notifications (
    id bigint NOT NULL,
    user_id bigint NOT NULL,
    title character varying(255) NOT NULL,
    message text NOT NULL,
    channel character varying(20) NOT NULL,
    is_read boolean NOT NULL,
    link character varying(255),
    created_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_notifications_channel CHECK (((channel)::text = ANY ((ARRAY['in_app'::character varying, 'email'::character varying])::text[])))
);
CREATE SEQUENCE public.notifications_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
ALTER SEQUENCE public.notifications_id_seq OWNED BY public.notifications.id;
CREATE TABLE public.step_runs (
    id bigint NOT NULL,
    workflow_run_id bigint NOT NULL,
    workflow_step_id bigint,
    step_order integer NOT NULL,
    step_type character varying(20) NOT NULL,
    step_snapshot jsonb NOT NULL,
    agent_id bigint,
    assigned_user_id bigint,
    status character varying(20) NOT NULL,
    retry_count integer NOT NULL,
    input_context jsonb,
    output_result jsonb,
    error_message text,
    started_at timestamp with time zone,
    finished_at timestamp with time zone,
    CONSTRAINT ck_step_runs_retry CHECK (((retry_count >= 0) AND (retry_count <= 1))),
    CONSTRAINT ck_step_runs_status CHECK (((status)::text = ANY ((ARRAY['pending'::character varying, 'in_progress'::character varying, 'done'::character varying, 'failed'::character varying])::text[])))
);
CREATE SEQUENCE public.step_runs_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
ALTER SEQUENCE public.step_runs_id_seq OWNED BY public.step_runs.id;
CREATE TABLE public.tasks (
    id bigint NOT NULL,
    title character varying(255) NOT NULL,
    description text NOT NULL,
    task_type character varying(20) NOT NULL,
    workflow_run_id bigint,
    step_run_id bigint,
    assigned_user_id bigint,
    assigned_agent_id bigint,
    created_by bigint,
    priority character varying(10) NOT NULL,
    status character varying(20) NOT NULL,
    deadline timestamp with time zone,
    result jsonb,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_tasks_priority CHECK (((priority)::text = ANY ((ARRAY['low'::character varying, 'medium'::character varying, 'high'::character varying])::text[]))),
    CONSTRAINT ck_tasks_status CHECK (((status)::text = ANY ((ARRAY['todo'::character varying, 'in_progress'::character varying, 'done'::character varying, 'failed'::character varying])::text[])))
);
CREATE SEQUENCE public.tasks_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
ALTER SEQUENCE public.tasks_id_seq OWNED BY public.tasks.id;
CREATE TABLE public.users (
    id bigint NOT NULL,
    email character varying(255) NOT NULL,
    password_hash character varying(255) NOT NULL,
    full_name character varying(255) NOT NULL,
    role character varying(20) NOT NULL,
    is_active boolean NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_users_role CHECK (((role)::text = ANY ((ARRAY['admin'::character varying, 'manager'::character varying, 'employee'::character varying])::text[])))
);
CREATE SEQUENCE public.users_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
ALTER SEQUENCE public.users_id_seq OWNED BY public.users.id;
CREATE TABLE public.workflow_runs (
    id bigint NOT NULL,
    workflow_id bigint NOT NULL,
    started_by bigint NOT NULL,
    status character varying(20) NOT NULL,
    current_step_order integer NOT NULL,
    initial_input jsonb NOT NULL,
    final_result jsonb,
    error_message text,
    started_at timestamp with time zone NOT NULL,
    finished_at timestamp with time zone,
    CONSTRAINT ck_workflow_runs_status CHECK (((status)::text = ANY ((ARRAY['running'::character varying, 'completed'::character varying, 'failed'::character varying, 'cancelled'::character varying])::text[])))
);
CREATE SEQUENCE public.workflow_runs_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
ALTER SEQUENCE public.workflow_runs_id_seq OWNED BY public.workflow_runs.id;
CREATE TABLE public.workflow_steps (
    id bigint NOT NULL,
    workflow_id bigint NOT NULL,
    step_order integer NOT NULL,
    step_type character varying(20) NOT NULL,
    name character varying(200) NOT NULL,
    agent_id bigint,
    assignee_role character varying(20),
    assignee_user_id bigint,
    config_json jsonb NOT NULL,
    CONSTRAINT ck_workflow_steps_order_positive CHECK ((step_order >= 1)),
    CONSTRAINT ck_workflow_steps_type CHECK (((step_type)::text = ANY ((ARRAY['agent'::character varying, 'user'::character varying, 'approval'::character varying])::text[])))
);
CREATE SEQUENCE public.workflow_steps_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
ALTER SEQUENCE public.workflow_steps_id_seq OWNED BY public.workflow_steps.id;
CREATE TABLE public.workflows (
    id bigint NOT NULL,
    name character varying(200) NOT NULL,
    description text NOT NULL,
    status character varying(20) NOT NULL,
    is_chat boolean NOT NULL,
    created_by bigint,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_workflows_status CHECK (((status)::text = ANY ((ARRAY['draft'::character varying, 'active'::character varying, 'inactive'::character varying])::text[])))
);
CREATE SEQUENCE public.workflows_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
ALTER SEQUENCE public.workflows_id_seq OWNED BY public.workflows.id;
ALTER TABLE ONLY public.activity_logs ALTER COLUMN id SET DEFAULT nextval('public.activity_logs_id_seq'::regclass);
ALTER TABLE ONLY public.agents ALTER COLUMN id SET DEFAULT nextval('public.agents_id_seq'::regclass);
ALTER TABLE ONLY public.knowledge_chunks ALTER COLUMN id SET DEFAULT nextval('public.knowledge_chunks_id_seq'::regclass);
ALTER TABLE ONLY public.knowledge_documents ALTER COLUMN id SET DEFAULT nextval('public.knowledge_documents_id_seq'::regclass);
ALTER TABLE ONLY public.notifications ALTER COLUMN id SET DEFAULT nextval('public.notifications_id_seq'::regclass);
ALTER TABLE ONLY public.step_runs ALTER COLUMN id SET DEFAULT nextval('public.step_runs_id_seq'::regclass);
ALTER TABLE ONLY public.tasks ALTER COLUMN id SET DEFAULT nextval('public.tasks_id_seq'::regclass);
ALTER TABLE ONLY public.users ALTER COLUMN id SET DEFAULT nextval('public.users_id_seq'::regclass);
ALTER TABLE ONLY public.workflow_runs ALTER COLUMN id SET DEFAULT nextval('public.workflow_runs_id_seq'::regclass);
ALTER TABLE ONLY public.workflow_steps ALTER COLUMN id SET DEFAULT nextval('public.workflow_steps_id_seq'::regclass);
ALTER TABLE ONLY public.workflows ALTER COLUMN id SET DEFAULT nextval('public.workflows_id_seq'::regclass);
ALTER TABLE ONLY public.activity_logs
    ADD CONSTRAINT activity_logs_pkey PRIMARY KEY (id);
ALTER TABLE ONLY public.agents
    ADD CONSTRAINT agents_pkey PRIMARY KEY (id);
ALTER TABLE ONLY public.knowledge_chunks
    ADD CONSTRAINT knowledge_chunks_pkey PRIMARY KEY (id);
ALTER TABLE ONLY public.knowledge_documents
    ADD CONSTRAINT knowledge_documents_pkey PRIMARY KEY (id);
ALTER TABLE ONLY public.notifications
    ADD CONSTRAINT notifications_pkey PRIMARY KEY (id);
ALTER TABLE ONLY public.step_runs
    ADD CONSTRAINT step_runs_pkey PRIMARY KEY (id);
ALTER TABLE ONLY public.tasks
    ADD CONSTRAINT tasks_pkey PRIMARY KEY (id);
ALTER TABLE ONLY public.knowledge_chunks
    ADD CONSTRAINT uq_knowledge_chunks_index UNIQUE (document_id, chunk_index);
ALTER TABLE ONLY public.workflow_steps
    ADD CONSTRAINT uq_workflow_steps_order UNIQUE (workflow_id, step_order);
ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_pkey PRIMARY KEY (id);
ALTER TABLE ONLY public.workflow_runs
    ADD CONSTRAINT workflow_runs_pkey PRIMARY KEY (id);
ALTER TABLE ONLY public.workflow_steps
    ADD CONSTRAINT workflow_steps_pkey PRIMARY KEY (id);
ALTER TABLE ONLY public.workflows
    ADD CONSTRAINT workflows_pkey PRIMARY KEY (id);
CREATE INDEX ix_activity_logs_created ON public.activity_logs USING btree (created_at);
CREATE INDEX ix_activity_logs_entity ON public.activity_logs USING btree (entity_type, entity_id, created_at);
CREATE INDEX ix_knowledge_chunks_document_id ON public.knowledge_chunks USING btree (document_id);
CREATE INDEX ix_knowledge_documents_collection ON public.knowledge_documents USING btree (collection, is_active);
CREATE INDEX ix_notifications_user_read ON public.notifications USING btree (user_id, is_read, created_at);
CREATE INDEX ix_step_runs_agent_finished ON public.step_runs USING btree (agent_id, finished_at);
CREATE INDEX ix_step_runs_run_status ON public.step_runs USING btree (workflow_run_id, status);
CREATE INDEX ix_tasks_assignee_status ON public.tasks USING btree (assigned_user_id, status);
CREATE INDEX ix_tasks_deadline ON public.tasks USING btree (deadline) WHERE (deadline IS NOT NULL);
CREATE UNIQUE INDEX ix_users_email ON public.users USING btree (email);
CREATE INDEX ix_workflow_runs_started_at ON public.workflow_runs USING btree (started_at);
CREATE INDEX ix_workflow_runs_started_by_started ON public.workflow_runs USING btree (started_by, started_at);
CREATE INDEX ix_workflow_runs_wf_status_started ON public.workflow_runs USING btree (workflow_id, status, started_at);
ALTER TABLE ONLY public.activity_logs
    ADD CONSTRAINT activity_logs_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);
ALTER TABLE ONLY public.agents
    ADD CONSTRAINT agents_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.users(id);
ALTER TABLE ONLY public.knowledge_chunks
    ADD CONSTRAINT knowledge_chunks_document_id_fkey FOREIGN KEY (document_id) REFERENCES public.knowledge_documents(id) ON DELETE CASCADE;
ALTER TABLE ONLY public.knowledge_documents
    ADD CONSTRAINT knowledge_documents_uploaded_by_fkey FOREIGN KEY (uploaded_by) REFERENCES public.users(id);
ALTER TABLE ONLY public.notifications
    ADD CONSTRAINT notifications_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);
ALTER TABLE ONLY public.step_runs
    ADD CONSTRAINT step_runs_agent_id_fkey FOREIGN KEY (agent_id) REFERENCES public.agents(id);
ALTER TABLE ONLY public.step_runs
    ADD CONSTRAINT step_runs_assigned_user_id_fkey FOREIGN KEY (assigned_user_id) REFERENCES public.users(id);
ALTER TABLE ONLY public.step_runs
    ADD CONSTRAINT step_runs_workflow_run_id_fkey FOREIGN KEY (workflow_run_id) REFERENCES public.workflow_runs(id) ON DELETE CASCADE;
ALTER TABLE ONLY public.step_runs
    ADD CONSTRAINT step_runs_workflow_step_id_fkey FOREIGN KEY (workflow_step_id) REFERENCES public.workflow_steps(id) ON DELETE SET NULL;
ALTER TABLE ONLY public.tasks
    ADD CONSTRAINT tasks_assigned_agent_id_fkey FOREIGN KEY (assigned_agent_id) REFERENCES public.agents(id);
ALTER TABLE ONLY public.tasks
    ADD CONSTRAINT tasks_assigned_user_id_fkey FOREIGN KEY (assigned_user_id) REFERENCES public.users(id);
ALTER TABLE ONLY public.tasks
    ADD CONSTRAINT tasks_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.users(id);
ALTER TABLE ONLY public.tasks
    ADD CONSTRAINT tasks_step_run_id_fkey FOREIGN KEY (step_run_id) REFERENCES public.step_runs(id) ON DELETE SET NULL;
ALTER TABLE ONLY public.tasks
    ADD CONSTRAINT tasks_workflow_run_id_fkey FOREIGN KEY (workflow_run_id) REFERENCES public.workflow_runs(id) ON DELETE SET NULL;
ALTER TABLE ONLY public.workflow_runs
    ADD CONSTRAINT workflow_runs_started_by_fkey FOREIGN KEY (started_by) REFERENCES public.users(id);
ALTER TABLE ONLY public.workflow_runs
    ADD CONSTRAINT workflow_runs_workflow_id_fkey FOREIGN KEY (workflow_id) REFERENCES public.workflows(id);
ALTER TABLE ONLY public.workflow_steps
    ADD CONSTRAINT workflow_steps_agent_id_fkey FOREIGN KEY (agent_id) REFERENCES public.agents(id);
ALTER TABLE ONLY public.workflow_steps
    ADD CONSTRAINT workflow_steps_assignee_user_id_fkey FOREIGN KEY (assignee_user_id) REFERENCES public.users(id);
ALTER TABLE ONLY public.workflow_steps
    ADD CONSTRAINT workflow_steps_workflow_id_fkey FOREIGN KEY (workflow_id) REFERENCES public.workflows(id) ON DELETE CASCADE;
ALTER TABLE ONLY public.workflows
    ADD CONSTRAINT workflows_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.users(id);
\unrestrict YeeOgJsucJxFT7q2nyfbCRQrOyHICHwrWZZttihacOSr4forrjarRyANx8B2rcQ
