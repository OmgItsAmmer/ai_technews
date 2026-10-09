"""Initial ai schema: articles, chunks, entities, stories, conversations, traces, evals.

Revision ID: 0001
Revises:
Create Date: 2026-10-09
"""

from alembic import op

from antix_ai.config import get_settings

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    dim = int(get_settings().embed_dim)
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    op.execute(
        f"""
        CREATE TABLE ai.story (
            id              bigserial PRIMARY KEY,
            headline        text NOT NULL,
            signature       text NOT NULL DEFAULT '',
            first_seen      timestamptz NOT NULL,
            last_updated    timestamptz NOT NULL,
            article_count   integer NOT NULL DEFAULT 0,
            source_count    integer NOT NULL DEFAULT 0,
            entity_ids      bigint[] NOT NULL DEFAULT '{{}}',
            centroid        vector({dim}),
            created_at      timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX story_last_updated_idx ON ai.story (last_updated DESC);
        CREATE INDEX story_entities_idx ON ai.story USING gin (entity_ids);

        CREATE TABLE ai.article (
            post_id         bigint PRIMARY KEY,
            content_hash    text NOT NULL,
            title           text NOT NULL,
            url             text,
            author          text,
            source_id       bigint,
            source_name     text,
            source_type     text,
            published_at    timestamptz,
            tags            text[] NOT NULL DEFAULT '{{}}',
            summary_short   text NOT NULL DEFAULT '',
            key_facts       jsonb NOT NULL DEFAULT '[]',
            event_signature text NOT NULL DEFAULT '',
            content_type    text NOT NULL DEFAULT 'news',
            importance      real NOT NULL DEFAULT 0.5,
            story_id        bigint REFERENCES ai.story(id) ON DELETE SET NULL,
            doc_embedding   vector({dim}),
            embed_model     text NOT NULL,
            enrich_model    text NOT NULL,
            indexed_at      timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX article_published_idx ON ai.article (published_at DESC NULLS LAST);
        CREATE INDEX article_source_idx ON ai.article (source_id, published_at DESC);
        CREATE INDEX article_story_idx ON ai.article (story_id);
        CREATE INDEX article_tags_idx ON ai.article USING gin (tags);
        CREATE INDEX article_doc_emb_idx ON ai.article
            USING hnsw (doc_embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64);

        CREATE TABLE ai.chunk (
            id                bigserial PRIMARY KEY,
            post_id           bigint NOT NULL REFERENCES ai.article(post_id) ON DELETE CASCADE,
            ord               integer NOT NULL,
            text              text NOT NULL,
            contextual_prefix text NOT NULL DEFAULT '',
            token_count       integer NOT NULL,
            embedding         vector({dim}) NOT NULL,
            tsv               tsvector NOT NULL,
            published_at      timestamptz,
            source_id         bigint,
            tags              text[] NOT NULL DEFAULT '{{}}',
            UNIQUE (post_id, ord)
        );
        CREATE INDEX chunk_embedding_idx ON ai.chunk
            USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64);
        CREATE INDEX chunk_tsv_idx ON ai.chunk USING gin (tsv);
        CREATE INDEX chunk_published_idx ON ai.chunk (published_at DESC NULLS LAST);
        CREATE INDEX chunk_source_idx ON ai.chunk (source_id);

        CREATE TABLE ai.entity (
            id              bigserial PRIMARY KEY,
            name            text NOT NULL,
            norm_name       text NOT NULL UNIQUE,
            type            text NOT NULL DEFAULT 'other',
            aliases         text[] NOT NULL DEFAULT '{{}}',
            mention_count   integer NOT NULL DEFAULT 0,
            first_seen      timestamptz NOT NULL DEFAULT now(),
            last_seen       timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX entity_aliases_idx ON ai.entity USING gin (aliases);
        CREATE INDEX entity_name_trgm_idx ON ai.entity USING gin (norm_name gin_trgm_ops);

        CREATE TABLE ai.article_entity (
            post_id     bigint NOT NULL REFERENCES ai.article(post_id) ON DELETE CASCADE,
            entity_id   bigint NOT NULL REFERENCES ai.entity(id) ON DELETE CASCADE,
            salience    real NOT NULL DEFAULT 0.5,
            PRIMARY KEY (post_id, entity_id)
        );
        CREATE INDEX article_entity_entity_idx ON ai.article_entity (entity_id);

        CREATE TABLE ai.conversation (
            id              text PRIMARY KEY,
            rolling_summary text NOT NULL DEFAULT '',
            focus           jsonb NOT NULL DEFAULT '{{}}',
            turn_count      integer NOT NULL DEFAULT 0,
            created_at      timestamptz NOT NULL DEFAULT now(),
            updated_at      timestamptz NOT NULL DEFAULT now()
        );

        CREATE TABLE ai.message (
            id              bigserial PRIMARY KEY,
            conversation_id text NOT NULL REFERENCES ai.conversation(id) ON DELETE CASCADE,
            role            text NOT NULL CHECK (role IN ('user', 'assistant')),
            content         text NOT NULL,
            citations       jsonb NOT NULL DEFAULT '[]',
            trace_id        uuid,
            created_at      timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX message_conv_idx ON ai.message (conversation_id, id);

        CREATE TABLE ai.trace (
            id          uuid PRIMARY KEY,
            kind        text NOT NULL,
            backend     text NOT NULL DEFAULT 'antix',
            session_id  text,
            query       text NOT NULL DEFAULT '',
            plan        jsonb,
            retrieved   jsonb,
            answer      text,
            verdict     jsonb,
            grounding   real,
            latency     jsonb,
            usage       jsonb,
            error       text,
            feedback    smallint,
            feedback_note text,
            created_at  timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX trace_created_idx ON ai.trace (created_at DESC);
        CREATE INDEX trace_low_grounding_idx ON ai.trace (grounding) WHERE grounding < 0.6;

        CREATE TABLE ai.eval_run (
            id          bigserial PRIMARY KEY,
            backend     text NOT NULL,
            dataset     text NOT NULL,
            git_sha     text,
            metrics     jsonb NOT NULL,
            cases       jsonb NOT NULL,
            created_at  timestamptz NOT NULL DEFAULT now()
        );
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS ai.eval_run, ai.trace, ai.message, ai.conversation,
            ai.article_entity, ai.entity, ai.chunk, ai.article, ai.story CASCADE;
        """
    )
