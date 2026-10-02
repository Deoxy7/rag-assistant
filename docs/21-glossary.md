# 21 — Glossary

**Status:** started in Phase 0 (2026-10-02); every phase appends its new terms. This is a reference page, so it does not use the 13-section skeleton.

One line per term, alphabetical. "Explained in" links to the doc that owns the concept; other docs link there instead of re-explaining it.

| Term | One-line definition | Explained in |
|---|---|---|
| `.env` file | A file of `KEY=value` lines loaded as environment variables; here read by both Compose and the app. | [03](03-environment-and-infra.md) |
| `pg_hba.conf` | Postgres' host-based authentication rules: who may connect from where, by which method. | [03](03-environment-and-infra.md) |
| `vector` type | pgvector's column type holding a fixed-length list of floats, e.g. `vector(384)`. | [03](03-environment-and-infra.md) |
| Ablation | Removing or swapping one component while holding everything else fixed, to measure what it contributes. | [02](02-architecture-overview.md) |
| Aborted transaction | A transaction in which a statement failed; Postgres rejects every further statement until rollback. | [03](03-environment-and-infra.md) |
| Abstention | Deliberately answering "not in the documents" when the evidence is too weak, instead of guessing. | [01](01-what-is-rag.md) |
| Anisotropy (embeddings) | Embedding vectors cluster in a narrow cone, so unrelated texts still have positive cosine (0.37 here). | [07](07-embeddings.md) |
| ANN (approximate nearest neighbour) | Search that visits part of an index and usually, not always, finds the true nearest vectors. | [08](08-database-schema.md) |
| Autocommit | Driver mode in which every statement is committed as its own transaction. | [03](03-environment-and-infra.md) |
| B-tree index | Sorted index for equality and range lookups (primary keys, hashes). | [08](08-database-schema.md) |
| Backend process | The Postgres server process started for each client connection. | [03](03-environment-and-infra.md) |
| Bi-encoder | Model that embeds query and passage separately, so passages can be embedded in advance. | [07](07-embeddings.md) |
| Bind address | The network interface a port listens on; `127.0.0.1` = this machine only, `0.0.0.0` = every interface. | [03](03-environment-and-infra.md) |
| BM25 | Ranking: Σ idf · tf·(k1+1)/(tf + k1·(1−b+b·len/avg)); rare terms count more, repeats saturate. | [10](10-keyword-search.md) |
| Born-digital PDF | A PDF whose pages contain real text drawing instructions (not pictures of text). | [04](04-corpus.md) |
| Bounding box (bbox) | Smallest rectangle around an element: (x0, y0, x1, y1) in PDF points, origin top-left. | [05](05-pdf-parsing.md) |
| Canonical text | One normalised string per document that every block and chunk offset indexes into. | [05](05-pdf-parsing.md) |
| cgroups | Linux kernel feature limiting how much CPU and memory a group of processes may use. | [03](03-environment-and-infra.md) |
| CHECK constraint | A condition every row must satisfy; violations abort the insert. | [08](08-database-schema.md) |
| Chunk | A passage of a document small enough to search precisely and to fit, several at a time, in a prompt. | [01](01-what-is-rag.md) |
| Chunk overlap | Repeating the last tokens of one chunk at the start of the next so boundary-cut sentences survive. | [06](06-chunking.md) |
| Chunking strategy | How boundaries are chosen: fixed windows, recursive (¶/line/sentence), structure-aware, semantic. | [06](06-chunking.md) |
| Citation | A pointer from a claim in an answer back to its source — here chunk id + page + character span. | [01](01-what-is-rag.md) |
| Closed-book / open-book | Answering from memory alone vs answering with the documents available. | [01](01-what-is-rag.md) |
| Closed-book baseline | The same golden questions answered with retrieval switched off; measures what retrieval adds. | [01](01-what-is-rag.md) |
| Colima | Open-source tool that runs a small Linux VM with a Docker engine on macOS. | [03](03-environment-and-infra.md) |
| Column gutter | A vertical strip no text crosses, separating two columns of text. | [05](05-pdf-parsing.md) |
| Container | Isolated processes sharing the host's kernel, with their own view of files, network and processes. | [03](03-environment-and-infra.md) |
| Content hash (sha256) | A 64-hex-character fingerprint of a file's bytes; any change alters it. | [04](04-corpus.md) |
| Content stream | A PDF page's drawing instructions (fonts, positions, glyphs) — not paragraphs. | [05](05-pdf-parsing.md) |
| Context window | The maximum number of tokens (input + output) a model can handle in one call. | [01](01-what-is-rag.md) |
| Contrastive training | Training that pulls matching pairs' vectors together and pushes non-matching ones apart. | [07](07-embeddings.md) |
| COPY | Postgres bulk-load command that streams many rows in one operation. | [08](08-database-schema.md) |
| Corpus manifest | A committed list of corpus files with source URL, size and sha256 (`data/manifest.json`). | [04](04-corpus.md) |
| Cosine similarity | a·b / (‖a‖‖b‖): cosine of the angle between vectors; equals the dot product for unit vectors. | [07](07-embeddings.md) |
| Cross-encoder | A model that reads the query and a passage *together* to score relevance; accurate but slower. | [12](12-reranking.md) (Phase 8) |
| Custom vs generic plan | Plan built with actual parameter values vs one cached plan built without them (after 5 executions). | [09](09-vector-search.md) |
| Dehyphenation | Rejoining a word hyphenated across a line break. | [05](05-pdf-parsing.md) |
| Digest | A sha256 hash of an image's content; unlike a tag it can never point at different bytes. | [03](03-environment-and-infra.md) |
| Distance operator | pgvector operator comparing two vectors: `<->` L2, `<=>` cosine distance, `<#>` negative inner product. | [03](03-environment-and-infra.md) |
| Docker Compose | A YAML file declaring containers, ports and volumes, and the command that makes them match it. | [03](03-environment-and-infra.md) |
| Document frequency (df) | Number of documents (chunks) containing a term. | [10](10-keyword-search.md) |
| Dot product | Sum of position-wise products: [1,2,3]·[4,5,6] = 32. | [07](07-embeddings.md) |
| ef_construction / ef_search / m | HNSW knobs: build-time candidate list, query-time candidate list, links per node. | [08](08-database-schema.md) |
| Embedding | A list of numbers representing a text's meaning, so that similar meanings are close together. | [07](07-embeddings.md) (Phase 4) |
| Embedding cache | Reusing a stored vector when identical text (same hash) and model appear again. | [07](07-embeddings.md) |
| Environment variable | A named value a process inherits from whoever started it. | [03](03-environment-and-infra.md) |
| Exhibit (10-K) | A document attached to a filing — contracts, plans, certifications — usually after the signature page. | [04](04-corpus.md) |
| Expression index | An index on an expression's result (embedding::vector(384)); queries must use the same expression. | [08](08-database-schema.md) |
| Extension (Postgres) | A package adding types, functions, operators or index types; enabled per database with `CREATE EXTENSION`. | [03](03-environment-and-infra.md) |
| Factory pattern | One function that turns configuration into the right implementation (`get_chunker`). | [06](06-chunking.md) |
| Fine-tuning | Continuing to train an already-trained model on new examples, changing its weights. | [01](01-what-is-rag.md) |
| Fiscal year | A company's accounting year, which need not match the calendar year. | [04](04-corpus.md) |
| Foreign key | A column that must match a primary key in another table. | [08](08-database-schema.md) |
| Form 10-K | The annual report US public companies file with the SEC, with a structure fixed by regulation. | [04](04-corpus.md) |
| Generated column | A column Postgres computes from other columns of the row (tsv from text). | [08](08-database-schema.md) |
| GIN index | Generalized Inverted Index: maps each element (lexeme) to the rows containing it. | [08](08-database-schema.md) |
| Glyph | A drawn character shape from a font; mapped back to Unicode during extraction. | [05](05-pdf-parsing.md) |
| Golden set | Questions whose correct answers and evidence locations are known in advance, used to score the system. | [15](15-eval-harness.md) (Phase 11) |
| Grounding | Making the model answer from supplied evidence: instructions, evidence placement and checks. | [01](01-what-is-rag.md) |
| Half-open range | [start, end): includes start, excludes end; length = end − start. | [05](05-pdf-parsing.md) |
| halfvec | pgvector's 16-bit float vector type; halves memory. | [09](09-vector-search.md) |
| Hallucination | Fluent output that no source supports, or that is simply false. | [01](01-what-is-rag.md) |
| Hamming distance | Number of differing bits between two bit strings; used for binary-quantised vectors. | [09](09-vector-search.md) |
| Hard negative | A non-relevant passage very similar to the relevant one (e.g. the same sentence from last year's filing). | [interview/04](interview/04-retrieval.md) |
| Heading level | 1 = PART, 2 = ITEM, 3 = other heading, 0 = not a heading. | [05](05-pdf-parsing.md) |
| Healthcheck | A command run periodically to decide whether a service is ready, not just running. | [03](03-environment-and-infra.md) |
| HNSW | Hierarchical Navigable Small World: layered proximity graph for approximate nearest-neighbour search. | [08](08-database-schema.md) |
| Idempotent | Doing it twice has the same effect as doing it once. | [03](03-environment-and-infra.md) |
| Idempotent ingestion | Re-running ingestion changes nothing that's already up to date. | [08](08-database-schema.md) |
| Identity column | Auto-assigned increasing id; values consumed by failed/conflicting inserts leave gaps. | [08](08-database-schema.md) |
| IDF (inverse document frequency) | ln(1 + (N − df + 0.5)/(df + 0.5)): high for rare terms. | [10](10-keyword-search.md) |
| Image (container) | A read-only, layered template from which containers are started. | [03](03-environment-and-infra.md) |
| Index (search) | A data structure built ahead of time so that search doesn't scan everything. | [01](01-what-is-rag.md) |
| Interleaving | When two fused lists don't overlap, RRF alternates them (#1, #1, #2, #2…), because equal ranks earn equal scores. | [11](11-hybrid-rrf.md) |
| Item (10-K) | A numbered section of a 10-K (Item 1A Risk Factors, Item 7 MD&A, Item 8 Financial Statements). | [04](04-corpus.md) |
| Iterative index scan | pgvector ≥ 0.8: keep walking HNSW until enough rows pass the filter. | [09](09-vector-search.md) |
| IVFFlat | Vector index that clusters vectors into lists and searches only the nearest lists. | [08](08-database-schema.md) |
| k1 / b (BM25) | Term-frequency saturation (1.2) and length normalisation (0.75). | [10](10-keyword-search.md) |
| Kernel | The core of an operating system: schedules processes, manages memory, talks to hardware. | [03](03-environment-and-infra.md) |
| Keyword (lexical) search | Search that matches the words themselves after normalising them. | [01](01-what-is-rag.md); details [10](10-keyword-search.md) |
| kNN (k-nearest neighbours) | Find the k stored vectors closest to a query; exact = compare with all. | [09](09-vector-search.md) |
| Latency | How long one request takes. | [02](02-architecture-overview.md) |
| Layering | Lower layers never depend on higher ones; enforced here by `tests/test_architecture.py`. | [02](02-architecture-overview.md) |
| Learned fusion | Combining retrievers with a model trained on labelled queries (features: scores, ranks, query type). | [11](11-hybrid-rrf.md) |
| Lexeme | A normalised word form stored by Postgres full-text search (e.g. "revenue" → `revenu`). | [10](10-keyword-search.md) (Phase 6); preview [03](03-environment-and-infra.md) |
| LLM (large language model) | A neural network trained to predict the next token of text. | [01](01-what-is-rag.md) |
| Long-context stuffing | Pasting whole documents into a large context window instead of retrieving passages. | [01](01-what-is-rag.md) |
| Lost in the middle | The finding that models use information in the middle of long inputs worse than at the edges (Liu et al., 2023). | [01](01-what-is-rag.md) |
| Make target / prerequisite | What Make builds, and what it must be newer than; a phony target is a command name, not a file. | [03](03-environment-and-infra.md) |
| Microservices | Each component deployed as its own network service. | [02](02-architecture-overview.md) |
| Migration | A numbered, ordered schema change applied once and recorded. | [08](08-database-schema.md) |
| Min-max normalisation | Rescaling a list's scores to 0–1 via (s − min)/(max − min); the best hit always becomes 1.0. | [11](11-hybrid-rrf.md) |
| Modular monolith | One deployable application divided into modules with enforced boundaries. | [02](02-architecture-overview.md) |
| MPS (Metal Performance Shaders) | PyTorch's backend for Apple GPUs. | [07](07-embeddings.md) |
| MVCC | Multi-version concurrency control: updates write new row versions; readers see committed versions. | [08](08-database-schema.md) |
| Namespaces | Linux kernel feature giving a process its own view of files, network and process ids. | [03](03-environment-and-infra.md) |
| NFKC normalisation | Unicode normal form that folds compatibility characters (non-breaking space, ligatures) to plain forms. | [05](05-pdf-parsing.md) |
| Non-breaking space | U+00A0, a space that looks normal but isn't to many tools; inflates token counts and breaks exact matching. | [04](04-corpus.md) |
| Non-parametric memory | Knowledge stored outside the model in a searchable index (term from Lewis et al., 2020). | [01](01-what-is-rag.md) |
| Norm | A vector's length: ‖[3,4]‖ = 5. | [07](07-embeddings.md) |
| Normalisation (vectors) | Dividing a vector by its norm so its length is 1. | [07](07-embeddings.md) |
| OCR (optical character recognition) | Recovering text from an image of text; needed only for scanned pages. | [04](04-corpus.md) |
| Offline path | Work done ahead of time that nobody waits for (parsing, chunking, embedding). | [02](02-architecture-overview.md) |
| Offset mapping | A fast tokenizer's per-token character spans; bridges token windows to character offsets. | [06](06-chunking.md) |
| Online path | Work done while a user waits (search, rank, generate). | [02](02-architecture-overview.md) |
| Parametric memory | Knowledge stored in a model's weights; fixed after training, uncitable. | [01](01-what-is-rag.md) |
| Parent-document retrieval | Match small child chunks, return the larger parent section they belong to. | [06](06-chunking.md) |
| Parser version (cache key) | Version string stored with parsed output; bumping it forces a re-parse. | [05](05-pdf-parsing.md) |
| Partial index | An index over only the rows matching a WHERE clause. | [08](08-database-schema.md) |
| PDF outline (bookmarks) | An optional table of contents stored inside a PDF; only Verizon's files have one here. | [04](04-corpus.md) |
| PDF point | 1/72 inch; a US Letter page is 612 × 792 points. | [05](05-pdf-parsing.md) |
| Percentile (p50 / p95 / p99) | The latency that 50% / 95% / 99% of requests beat; p50 is the median. | [02](02-architecture-overview.md) |
| pgvector | Postgres extension adding a `vector` type, distance operators and HNSW / IVFFlat indexes. | [03](03-environment-and-infra.md) |
| Phrase query | Terms that must be adjacent and in order: 'net' <-> 'revenu'. | [10](10-keyword-search.md) |
| Pinning | Fixing a dependency to an exact version (`==`) so installs are reproducible. | [03](03-environment-and-infra.md) |
| Pipeline / stage | A sequence of steps where each step's output feeds the next; each step is a stage. | [02](02-architecture-overview.md) |
| Pooling | Turning per-token vectors into one text vector (bge: the [CLS] vector). | [07](07-embeddings.md) |
| Port publishing | Making a container's port reachable from the host, e.g. `127.0.0.1:5432:5432`. | [03](03-environment-and-infra.md) |
| Post-filter / pre-filter | Apply metadata conditions after vs before the vector search. | [09](09-vector-search.md) |
| Prepared statement | A statement parsed/planned once and executed many times; psycopg auto-prepares after 5 runs. | [09](09-vector-search.md) |
| Primary key | Column(s) that uniquely identify a row. | [08](08-database-schema.md) |
| Protocol (Python typing) | An interface defined by attributes/methods; any class with them qualifies, no inheritance. | [06](06-chunking.md) |
| QPS | Queries per second. | [02](02-architecture-overview.md) |
| Quantisation | Storing vector numbers with fewer bits (float16, 1-bit) to save memory. | [09](09-vector-search.md) |
| Query instruction | Prefix bge v1.5 expects on queries: 'Represent this sentence for searching relevant passages: '. | [07](07-embeddings.md) |
| Query planner | The Postgres component that picks a plan (indexes, join order) by estimated cost. | [09](09-vector-search.md) |
| Query routing | Sending each query to the retriever suited to its type (e.g. figures → keyword) instead of fusing. | [11](11-hybrid-rrf.md) |
| RAG (Retrieval-Augmented Generation) | Retrieve relevant passages at question time, then have the LLM answer from them with citations. | [01](01-what-is-rag.md) |
| Rank fusion | Merging several ranked lists into one ranking. | [11](11-hybrid-rrf.md) |
| Re-embedding migration | Recomputing every vector for a new model, side by side, before switching queries. | [07](07-embeddings.md) |
| Reading order | The order a human reads blocks in; reconstructed from positions. | [05](05-pdf-parsing.md) |
| Recall cliff | Fewer than k (or zero) results when a selective filter runs after an approximate search. | [09](09-vector-search.md) |
| Reranker | A slower, more accurate model that re-orders the top candidates from retrieval. | [12](12-reranking.md) (Phase 8) |
| Retrieval | Finding the passages most relevant to a query. | [01](01-what-is-rag.md) |
| Retrieval depth | How many results each retriever returns before fusion (50 here); must exceed the final k. | [11](11-hybrid-rrf.md) |
| Role (Postgres) | A database user identity you log in as. | [03](03-environment-and-infra.md) |
| RRF (Reciprocal Rank Fusion) | Merging ranked lists by summing 1 / (k + rank) for each item across lists. | [11](11-hybrid-rrf.md) |
| RRF k constant | Added to every rank before inverting; small k favours each list's top hit, large k favours agreement (k = 60 default). | [11](11-hybrid-rrf.md) |
| Ruled / unruled table | A table drawn with lines (found by pdfplumber's default strategy) vs one aligned by spacing only. | [05](05-pdf-parsing.md) |
| Running header / footer | A line repeated at the top or bottom of most pages; noise for search. | [04](04-corpus.md) |
| Running-header fingerprint | Band text with digits → '#' and leading/trailing page numbers removed, used to detect repeats. | [05](05-pdf-parsing.md) |
| Savepoint | A nested transaction marker; psycopg's nested conn.transaction() creates one. | [09](09-vector-search.md) |
| Scanned PDF page | A page that is a picture of text: an image and little or no extractable text. | [04](04-corpus.md) |
| SCRAM-SHA-256 | Challenge-response password authentication; the password never crosses the network readably. | [03](03-environment-and-infra.md) |
| Section path | The chain of headings a block sits under, e.g. PART II › ITEM 8 › … | [05](05-pdf-parsing.md) |
| Semantic chunking | Cutting text where similarity between consecutive sentence embeddings drops. | [06](06-chunking.md) |
| SET LOCAL | Change a setting until the end of the current top-level transaction. | [09](09-vector-search.md) |
| Span / line / block (PyMuPDF) | Run of text in one font / spans on one baseline / lines grouped by PyMuPDF. | [05](05-pdf-parsing.md) |
| Special tokens ([CLS], [SEP]) | Tokens a BERT-style model adds around every input; they count against its 512-token limit. | [06](06-chunking.md) |
| SSE (Server-Sent Events) | A one-way HTTP stream of events from server to client, used to stream answer tokens. | [14](14-api-and-streaming.md) (Phase 10) |
| Stamp file | An empty file whose timestamp tells Make when a step last ran. | [03](03-environment-and-infra.md) |
| Stemming | Rule-based cutting of words to a stem; can err ('Corning' → 'corn'). | [10](10-keyword-search.md) |
| Stop word | A very common word ("the", "were") dropped by full-text search. | [10](10-keyword-search.md) (Phase 6); preview [03](03-environment-and-infra.md) |
| Strategy pattern | Interchangeable implementations behind one interface (the three chunkers). | [06](06-chunking.md) |
| Tag (image) | A movable, human-readable name for an image version. | [03](03-environment-and-infra.md) |
| Tail latency | The slow end of the latency distribution (p95, p99) that averages hide. | [02](02-architecture-overview.md) |
| Term frequency (tf) | Occurrences of a term in a document. | [10](10-keyword-search.md) |
| Text extractability | How much text extraction actually yields from a page. | [04](04-corpus.md) |
| Throughput | How many requests per second a system can complete. | [02](02-architecture-overview.md) |
| Tie-break | The rule ordering equal scores; RRF here uses best single rank, then chunk id, for reproducible order. | [11](11-hybrid-rrf.md) |
| Time to first token (TTFT) | Time until the first word of an answer appears. | [02](02-architecture-overview.md) |
| Token | The unit of text an LLM reads, writes and bills by — a word or part of a word. | [01](01-what-is-rag.md) |
| Tokenizer | The program that splits text into a model's tokens. | [01](01-what-is-rag.md) |
| Top-k | The k highest-scoring results of a search. | [01](01-what-is-rag.md) |
| Training cutoff | The date a model's training data ends. | [01](01-what-is-rag.md) |
| Transaction | A group of statements that all happen or none do. | [03](03-environment-and-infra.md) |
| Transitive dependency | A package required by your packages rather than by your code directly. | [03](03-environment-and-infra.md) |
| Truncation | Silently dropping input beyond a model's token limit. | [06](06-chunking.md) |
| ts_rank / ts_rank_cd | Postgres rankings by term frequency / by cover density (proximity); neither uses IDF. | [10](10-keyword-search.md) |
| tsquery | Postgres boolean query over lexemes: & AND, | OR, ! NOT, <-> followed by. | [10](10-keyword-search.md) |
| tsvector | Postgres type holding a document's lexemes with their positions. | [10](10-keyword-search.md) (Phase 6); preview [03](03-environment-and-infra.md) |
| Twelve-factor app | A set of service-design principles, including "store config in the environment". | [03](03-environment-and-infra.md) |
| Unix socket | A file that acts as a network connection between programs on the same machine. | [03](03-environment-and-infra.md) |
| VACUUM | Postgres process that removes dead row versions and their index entries. | [08](08-database-schema.md) |
| Vector (semantic) search | Search by nearness of embeddings, so paraphrases match. | [01](01-what-is-rag.md); details [09](09-vector-search.md) |
| Virtual environment (venv) | A per-project Python with its own installed packages. | [03](03-environment-and-infra.md) |
| Virtual machine (VM) | Software emulating a whole computer, running its own kernel. | [03](03-environment-and-infra.md) |
| Volume | Docker-managed storage that outlives containers; holds our database files. | [03](03-environment-and-infra.md) |
| Weighted-score fusion | Normalise each list's scores, then take a weighted sum; needs a tuned weight. | [11](11-hybrid-rrf.md) |
| WordPiece | BERT's subword tokenizer; continuation pieces are marked ## (16,434 → 16 , 43 ##4). | [06](06-chunking.md) |
| Workload contract | The answers to: how big, how often, how many, who sees what, what if unsure, which latency matters. | [02](02-architecture-overview.md) |
