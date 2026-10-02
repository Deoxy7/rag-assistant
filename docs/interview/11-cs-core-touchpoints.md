# 11 — CS core touchpoints

**Status:** started in Phase 0 (2026-10-02). Questions are appended each phase. Planned coverage: OS (processes vs threads, the GIL, async I/O, memory in embedding batches, page cache — Phases 4, 10); DBMS (ACID, indexes, query planning, deadlocks — Phases 4–6); networking (HTTP/1.1 vs 2, TCP, SSE over HTTP, timeouts, keep-alive — Phase 10); design patterns actually used in the repo with real class names (strategy for chunkers, repository for storage, factory for retrievers — Phases 3–7); complexity of each pipeline stage; DSA that naturally follows (top-k heaps, merging ranked lists, dedup, LRU cache).

---

### Q: What's the difference between a container and a VM? Why does Docker on a Mac need a VM?
**ID:** P0-13 · **Round:** viva · backend screen  **Difficulty:** 2/5

**30-second answer.** "A VM emulates a whole computer and runs its own operating-system kernel. A container is just ordinary processes on the host's kernel, isolated so they see their own files, network and process list, and limited in the CPU and memory they can use. Linux containers need a Linux kernel; macOS's kernel isn't Linux, so on a Mac a small Linux VM — Colima in my case — runs underneath, and the containers run inside it."

**2-minute answer.** Name the two Linux mechanisms: **namespaces** (what a process can *see*: its own mount table, network stack, process ids) and **cgroups** (what it can *use*: CPU, memory limits). That's why containers start in about a second — no OS to boot — and why they're lighter than VMs. Then the layering on this machine: macOS → Apple Virtualization framework → Colima's Linux VM (2 CPU, 2 GB) → Docker engine → the Postgres container. Measured: the VM's first start took 13 min 17 s (downloading its image), later starts 44 s; the container itself becomes healthy in about 6 s.

**If they push — level 2.** *"What's the security difference?"* A VM has a hard boundary — a separate kernel — so escaping it means breaking the hypervisor. Containers share the host kernel, so a kernel vulnerability can break isolation. That's why multi-tenant clouds often run containers *inside* VMs.

**If they push — level 3.** *"What is an image, really?"* A stack of read-only filesystem layers plus metadata (entry command, environment). Containers add a thin writable layer on top; deleting the container deletes that layer, which is why database files go in a volume.

**If they push — level 4.** *"How does the port forward from your Mac reach Postgres?"* The container's port 5432 is published by Docker inside the VM, and Colima forwards the VM's port to `127.0.0.1:5432` on the Mac. From Postgres's point of view, our connection arrives from the Docker bridge gateway (172.18.0.1). I know the observable behaviour; I haven't studied Colima's forwarding implementation.

**Whiteboard it.**
```text
 VM:         [ app | OS kernel ] on hypervisor          ← own kernel
 container:  [ app ] [ app ] on ONE shared Linux kernel ← namespaces + cgroups
 my Mac:     macOS → Colima Linux VM → Docker → Postgres container
```

**Trap.** "Containers are lightweight VMs." They aren't VMs at all — no separate kernel — and saying so suggests you've never had to explain why Docker on a Mac needs one.

**Bridge.** "Running the database in a container but the app on the host was a deliberate split — fast edit loop for the app, reproducibility for the database."

---

### Q: How do you make a Python project reproducible across machines?
**ID:** P0-14 · **Round:** backend screen · viva  **Difficulty:** 2/5

**30-second answer.** "Pin every layer. The database image by tag *and* digest; every Python package with `==`, including transitive dependencies; the Python version itself, named explicitly in the Makefile because this machine's default `python3` is 3.14; and setup reduced to one command. Then tests that check the environment — like the pgvector version — so drift fails loudly by name."

**2-minute answer.** Explain each piece and what breaks without it. Tag alone: the publisher can re-push it, so two pulls a month apart may differ; the digest is a content hash. Direct-only pins: transitive dependencies (pydantic under pydantic-settings) change underneath you. Unnamed Python: `python3 -m venv` silently builds a 3.14 venv. Then the Makefile's stamp file: requirements reinstall automatically when `requirements.txt` changes, because the stamp is older. And why it matters for *this* project specifically: the deliverable is numbers, and an environment change between two runs would be indistinguishable from a code change.

**If they push — level 2.** *"Why not a lock file tool like Poetry or uv?"* They generate the same thing — exact versions for everything, plus hashes — with better ergonomics. The plan pinned plain `requirements.txt`; a lock tool would add hash checking, which protects against a tampered package with the same version number. I'd adopt one in a team.

**If they push — level 3.** *"What does hash pinning add over version pinning?"* A version number is a name; a hash is the content. If a package index were compromised and a different file served under the same version, a hash check would refuse to install it.

**If they push — level 4.** *"Is anything still not reproducible?"* Yes: the host OS and CPU architecture (arm64 here — some wheels differ by platform), the Colima VM image, and anything downloaded at runtime later, such as model weights from a hub — those need pinning by revision in Phase 4. Model inference can also differ slightly between CPU and Apple's GPU, which I plan to measure.

**Whiteboard it.**
```text
 image:     tag + @sha256 digest         python: python3.11 (not python3)
 packages:  == for direct + transitive   setup:  make test (one command)
 verify:    tests assert pgvector == 0.8.7, password enforced
```

**Trap.** "Docker makes everything reproducible." Our app doesn't even run in Docker; reproducibility comes from pinning every layer, Docker being one of them.

**Bridge.** "The same idea is why the eval runner will write timestamped, never-overwritten results — reproducible numbers, not just reproducible installs."
