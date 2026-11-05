# Ceph MDS Zero-Downtime Upgrade ("Vampire") — Phase 1 Specification

## 1. Problem Statement & Objective

### 1.1 Status Quo Issues
Fast Metadata Server (MDS) upgrades in Ceph currently suffer from two major architectural limitations:
1. **Cross-Version Incompatibility:** Older and newer versions of the MDS daemon cannot reliably operate concurrently within the same CephFS cluster without risking metadata loss, daemon crashes, or wire protocol/encoding incompatibilities.
2. **Failover Downtime:** Any failover triggered to upgrade an MDS rank introduces service downtime for all subtrees for which that rank is authoritative, and disrupts operations where that rank replicates metadata.

### 1.2 Phase 1 Goal: Monitor-Assisted Workload Draining
To achieve a zero-downtime MDS upgrade, Phase 1 leverages Ceph's existing subtree migration infrastructure so an MDS rank sheds its workload ("draining") before being replaced:
- Monitors track draining lifecycle states via two new sets in `MDSMap`: `MDSMap::draining` (ranks actively shedding workload) and `MDSMap::drained` (unavailable ranks that have completed draining).
- Any rank in `MDSMap::draining` that starts or recovers enters `up:draining` instead of `up:active`.
- Ephemeral pinning excludes `up:draining` and `up:drained` ranks from target selection, redistributing ephemerally pinned subtrees across active ranks while remaining subtrees migrate to `rank 0`.
- An `up:draining` rank behaves like `up:stopping`—migrating all authoritative metadata and flushing its entire metadata journal—before sending `up:drained` (instead of `up:stopped`) to the Monitors.
- Upon receiving `up:drained`, the Monitors remove the daemon from the `MDSMap` and move the rank from `MDSMap::draining` to `MDSMap::drained`. No standby daemon is promoted to that rank until `ceph fs clear-drain` removes it from `MDSMap::drained`.
- Once cleared, a replacement daemon starts with a clean journal, no cached state, and no client sessions, reaching `up:active` in seconds and reclaiming its ephemerally and statically pinned subtrees.

> **Note on Scope:** Phase 1 focuses purely on Monitor-assisted workload draining and recovery (`up:draining` -> `up:drained` -> `ceph fs clear-drain`). Modifying standby selection logic to prefer higher-versioned MDS daemons is deferred to **Phase 2**. Phase 1 alone enables production performance evaluation of zero-downtime draining under heavy metadata load without upgrading the MDS binary.

---

## 2. Shared Contracts & State Machine Invariants

All LLM agents working on this feature must adhere to the following shared definitions to ensure clean integration across Monitor and MDS subsystems:

### 2.1 Daemon States & `MDSMap` Sets
```
Normal Activation:
  up:starting / up:rejoin / up:clientreplay  --->  up:active

When rank is in MDSMap::draining:
  up:starting / up:rejoin / up:clientreplay  --->  up:draining
  up:active (when drain command issued)      --->  up:draining

Draining Completion:
  up:draining (MDS flushes journal & subtrees) --[MMDSBeacon(STATE_DRAINED)]--> Mon
  Mon removes daemon from MDSMap, moves rank: MDSMap::draining ---> MDSMap::drained

Drain Clearing (`ceph fs clear-drain`):
  Rank removed from MDSMap::drained ---> Standby promoted ---> up:starting ---> up:active
```

### 2.2 Canonical Identifiers (Proposed Contract)
- **Daemon States (`MDSMap::DaemonState` / `ceph_fs.h`):**
  - `CEPH_MDS_STATE_DRAINING` / `MDSMap::STATE_DRAINING` (string representation: `"up:draining"`)
  - `CEPH_MDS_STATE_DRAINED` / `MDSMap::STATE_DRAINED` (string representation: `"up:drained"`)
- **`MDSMap` Member Sets (`src/mds/MDSMap.h`):**
  - `std::set<mds_rank_t> draining;`
  - `std::set<mds_rank_t> drained;`
- **`MDSMap` Query Helpers:**
  - `bool is_draining(mds_rank_t r) const`
  - `bool is_drained(mds_rank_t r) const`
  - `bool is_stopping_or_draining(mds_rank_t r) const`
  - `const std::set<mds_rank_t>& get_draining_mds_set() const`
  - `const std::set<mds_rank_t>& get_drained_mds_set() const`

---

## 3. Multi-Agent Workstream Breakdown & Dependency Graph

| Agent ID | Workstream Name | Primary Directories / Files | Depends On | Can Run In Parallel With |
| :--- | :--- | :--- | :--- | :--- |
| **Agent 1** | `MDSMap` & Wire Protocol Foundations | `src/include/ceph_fs.h`, `src/mds/MDSMap.h`, `src/mds/MDSMap.cc` | None (Foundation) | None (Run first or stub headers) |
| **Agent 2** | Monitor Orchestration & CLI Commands | `src/mon/MDSMonitor.*`, `src/mon/FSCommands.cc`, `src/mon/MonCommands.h` | Agent 1 | Agent 3, Agent 4 |
| **Agent 3** | Subtree Migration & Ephemeral Pinning | `src/mds/MDBalancer.*`, `src/mds/MDCache.*`, `src/mds/Migrator.*` | Agent 1 | Agent 2, Agent 4 |
| **Agent 4** | MDS Daemon Draining Lifecycle | `src/mds/MDSRank.*`, `src/mds/Server.*`, `src/mds/MDLog.*`, `src/mds/Beacon.*` | Agent 1, Agent 3 (interfaces) | Agent 2 |
| **Agent 5** | QA, Fault Injection & Load Testing | `qa/tasks/cephfs/`, `qa/suites/fs/` | Agents 1–4 | Test scaffolding can start early |

---

## 4. Detailed Agent Specifications

### Agent 1: `MDSMap` & Wire Protocol Foundations

#### Scope & Target Files
- `src/include/ceph_fs.h`
- `src/mds/MDSMap.h`
- `src/mds/MDSMap.cc`

#### Implementation Steps
1. **Define New Daemon States:**
   - Add `CEPH_MDS_STATE_DRAINING` and `CEPH_MDS_STATE_DRAINED` to `src/include/ceph_fs.h` and map them in `MDSMap::DaemonState` (`src/mds/MDSMap.h`).
   - Update `ceph_mds_state_name()` in `src/mds/MDSMap.cc` to return `"up:draining"` for `STATE_DRAINING` and `"up:drained"` for `STATE_DRAINED`.
2. **Add `draining` and `drained` Sets to `MDSMap`:**
   - Declare `std::set<mds_rank_t> draining;` and `std::set<mds_rank_t> drained;` in `MDSMap`.
   - Implement accessor and mutation helpers:
     - `is_draining(mds_rank_t r)`, `is_drained(mds_rank_t r)`
     - `mark_draining(mds_rank_t r)` (inserts into `draining`, ensures not in `drained`)
     - `mark_drained(mds_rank_t r)` (erases from `draining`, inserts into `drained`)
     - `clear_drain(mds_rank_t r)` (erases from both `draining` and `drained`)
   - Update rank query helpers (`get_MDS_set`, `is_active_or_stopping`, etc.) so callers that treat `up:stopping` as an active metadata participant during shutdown can also include `up:draining`.
3. **Update Serialization & Formatting:**
   - Bump the `ENCODE_START` struct version in `MDSMap::encode()` and decode `draining` and `drained` sets conditionally based on `struct_v` in `MDSMap::decode()`.
   - Update `MDSMap::dump()` (JSON/formatter output) and `MDSMap::print()` / `MDSMap::print_summary()` so `ceph fs status` and `ceph fs dump` display `draining` and `drained` ranks.

#### Unclear Details & Open Questions (Agent 1)
- **Wire Protocol / Feature Bits:** It is unclear whether adding `draining` and `drained` sets to `MDSMap` requires a new Ceph feature bit (e.g., `CEPH_FEATURE_MDS_DRAIN`) or if bumping the `MDSMap` internal `struct_v` encoding version on the server side is sufficient, and whether older clients (`libcephfs` / kernel client) decode `MDSMap` state enums strictly when encountering `CEPH_MDS_STATE_DRAINING`.
- **Client `MDSMap` Visibility:** When an MDS rank is in `up:draining`, clients still hold sessions with it until migrated. We need to confirm whether older kernel/FUSE clients reject or mishandle an MDS in `CEPH_MDS_STATE_DRAINING` when routing cap flushes or session closes, or if `up:draining` should be masked as `up:stopping` in client-facing `MDSMap` encodings.

---

### Agent 2: Monitor Orchestration & CLI Commands

#### Scope & Target Files
- `src/mon/MonCommands.h`
- `src/mon/FSCommands.cc`
- `src/mon/MDSMonitor.h`
- `src/mon/MDSMonitor.cc`

#### Implementation Steps
1. **Add Monitor CLI Commands:**
   - Implement the command to initiate draining on a target rank (e.g., `ceph fs drain <fs_name> <rank>`).
   - Implement `ceph fs clear-drain <fs_name> [<rank>|--all]` to remove one or all ranks from `MDSMap::drained` (and `MDSMap::draining` if cancelling an in-progress drain).
   - Register command signatures and permissions in `src/mon/MonCommands.h` and handlers in `src/mon/FSCommands.cc`.
2. **Transition Ranks into `MDSMap::draining` and `up:draining`:**
   - When the drain command is executed on rank `r`:
     - Add `r` to `MDSMap::draining`.
     - If rank `r` is currently `up:active`, transition its state in `MDSMap` to `MDSMap::STATE_DRAINING` (`up:draining`).
   - Modify state progression in `MDSMonitor` (specifically where ranks transition from `up:starting`, `up:rejoin`, or `up:clientreplay` to `up:active`):
     - Check `mdsmap.is_draining(rank)`. If true, transition the rank to `MDSMap::STATE_DRAINING` (`up:draining`) instead of `MDSMap::STATE_ACTIVE` (`up:active`).
3. **Handle `up:drained` Beacon from MDS:**
   - In `MDSMonitor::prepare_beacon()`, handle `STATE_DRAINED` from a rank in `STATE_DRAINING` (mirroring the `STATE_STOPPED` handler for `STATE_STOPPING`):
     - Remove the daemon's `mds_info_t` from `MDSMap` (or return it to standby/shutdown as appropriate).
     - Move the rank from `MDSMap::draining` to `MDSMap::drained` (`mdsmap.mark_drained(rank)`).
4. **Block Standby Promotion for Drained Ranks:**
   - In `MDSMonitor::maybe_promote_standby()` and failover scanning routines, ensure ranks present in `MDSMap::drained` are **never** assigned a standby daemon.
   - Only when `ceph fs clear-drain` removes the rank from `MDSMap::drained` should `maybe_promote_standby()` assign a standby to bring the rank back through `up:starting` -> `up:active`.

#### Unclear Details & Open Questions (Agent 2)
- **Exact CLI Syntax for Starting Drain & `clear-drain`:** The spec explicitly mentions `ceph fs clear-drain`, but does not specify the exact command signature for *starting* a drain (e.g., `ceph fs drain <fs_name> <rank>` vs. `ceph mds drain <role>`) or whether `ceph fs clear-drain` takes `<fs_name> <rank>` or clears all drained ranks in `<fs_name>`.
- **Post-Drain Daemon Fate:** Once the draining MDS sends `up:drained` and the Monitor removes it from the `MDSMap`, it is unclear whether the old MDS daemon process should terminate (`suicide()`/`respawn()`) so the orchestrator (`cephadm`) can upgrade the container, or if it enters `up:standby` (which could accidentally get re-promoted in Phase 1 before Phase 2's version-aware standby selection exists).
- **Interaction with `max_mds`:** Normally, `up:stopping` is triggered by reducing `max_mds`, and `STATE_STOPPED` expects `rank >= max_mds`. Since `up:draining` happens on a rank where `rank < max_mds`, all `MDSMonitor` assertions checking `rank >= max_mds` on stopping/stopped transitions must be audited so they do not trip on `up:draining` / `up:drained`.

---

### Agent 3: Subtree Migration & Ephemeral Pinning

#### Scope & Target Files
- `src/mds/MDBalancer.h`
- `src/mds/MDBalancer.cc`
- `src/mds/MDCache.h`
- `src/mds/MDCache.cc`
- `src/mds/Migrator.h`
- `src/mds/Migrator.cc`

#### Implementation Steps
1. **Exclude `draining` and `drained` Ranks from Ephemeral Pinning Targets:**
   - Locate ephemeral pin target computation in `MDCache` / `MDBalancer` (both Distributed Ephemeral Pinning and Random Ephemeral Pinning consistent hash rings).
   - Filter out any rank `r` where `mdsmap->is_draining(r)` or `mdsmap->is_drained(r)` when constructing the list/ring of valid target ranks.
   - Ensure that when `MDSMap` updates with a newly draining or newly re-activated rank, the ephemeral pin target table recalculates and triggers migrations:
     - Away from the `up:draining` rank to remaining `up:active` ranks during drain.
     - Back to the rank once it returns to `up:active` after `clear-drain`.
2. **Migrate Remaining Authoritative Subtrees to Rank 0:**
   - For all non-ephemerally pinned subtrees authoritative on the `up:draining` rank, trigger subtree exports to `rank 0` using the existing `MDCache::shutdown_pass()` / `Migrator::export_dir()` logic used by `up:stopping`.
3. **Prevent Incoming Migrations to `up:draining` Ranks:**
   - In `MDBalancer` and `Migrator`, reject or suppress any load-balancing or pin-based imports targeting a rank in `STATE_DRAINING` or in `MDSMap::draining` / `MDSMap::drained`.

#### Unclear Details & Open Questions (Agent 3)
- **Draining `rank 0`:** The specification states: *"the MDS will migrate its ephemerally pinned subtrees across the MDS cluster, and migrate all others to rank 0."* It is unclear how **Rank 0 itself** can be drained if Rank 0 is the hardcoded destination for non-ephemerally pinned subtrees and root metadata (`MDS_INO_ROOT`). If Rank 0 is placed in `up:draining`, another active rank (e.g., the lowest-numbered `up:active` rank not in `draining`/`drained`) would need to accept Rank 0's subtrees, or Rank 0 must be restricted/handled specially.
- **Statically Pinned Directories (`ceph.dir.pin`):** If a user has explicitly set a static export pin (`setfattr -n ceph.dir.pin -v <rank>`) to the rank being drained, `MDBalancer` normally refuses to move it or immediately migrates it back. We must confirm that `up:draining` overrides static `ceph.dir.pin` during drain (migrating it to `rank 0`) while preserving the `ceph.dir.pin` inode attribute so it automatically returns once the rank returns to `up:active`.
- **All Ranks Draining Simultaneously:** If an operator attempts to drain all ranks (or all remaining active ranks), ephemeral pin target selection will have an empty target set. Monitor CLI validation (Agent 2) and `MDBalancer` (Agent 3) must define a fallback or forbid draining the last remaining `up:active` rank.

---

### Agent 4: MDS Daemon Draining Lifecycle (`up:draining` -> `up:drained`)

#### Scope & Target Files
- `src/mds/MDSRank.h`
- `src/mds/MDSRank.cc`
- `src/mds/MDCache.cc`
- `src/mds/Server.cc`
- `src/mds/MDLog.cc`
- `src/mds/Beacon.cc`

#### Implementation Steps
1. **Unify `up:stopping` and `up:draining` Execution Paths in `MDSRank`:**
   - Add `bool MDSRank::is_draining() const { return state == MDSMap::STATE_DRAINING; }` and `bool MDSRank::is_stopping_or_draining() const { return is_stopping() || is_draining(); }`.
   - Audit all call sites of `mds->is_stopping()` across `MDSRank`, `MDCache`, `Migrator`, `Server`, `Locker`, and `MDLog`. Replace with `is_stopping_or_draining()` wherever the behavior applies to workload shedding, subtree export, session eviction/import, and journal flushing.
2. **Initiate Draining on State Transition:**
   - In `MDSRankDispatcher::handle_mds_map()`, handle transition into `MDSMap::STATE_DRAINING`:
     - If transitioning from `STATE_ACTIVE` (or from recovery states `STATE_REJOIN` / `STATE_CLIENTREPLAY` / `STATE_STARTING` when in `MDSMap::draining`), invoke the shutdown/drain initiation path (`stopping_start()` / `mdcache->shutdown_start()`).
3. **Flush Journal and Evict/Migrate Client Sessions:**
   - Ensure `MDCache::shutdown_pass()` exports all authoritative subtrees, flushes all dirty metadata and `MDLog` journal segments, and closes/migrates all client sessions cleanly so the on-disk journal is empty.
4. **Emit `up:drained` Instead of `up:stopped`:**
   - In `MDSRank::stopping_done()`:
     - Branch on current state:
       - If `is_stopping()`, keep existing behavior: `beacon.set_want_state(mdsmap, MDSMap::STATE_STOPPED)`.
       - If `is_draining()`, call `beacon.set_want_state(mdsmap, MDSMap::STATE_DRAINED)`.
   - Ensure `Beacon` permits `STATE_DRAINED` as a valid target state and waits for Monitor acknowledgment before shutting down or resetting the daemon.

#### Unclear Details & Open Questions (Agent 4)
- **Stray Directory (`~mdsN`) Handling:** When a rank stops (`up:stopping`), it migrates entries in its stray directory (`~mdsN`) to another rank (`MDCache::migrate_strays()`). However, for `up:draining`, the rank number `N` will soon return to `up:active` ( unlike `up:stopping` where `max_mds` shrunk). We need to confirm whether `~mdsN` still needs to have all its stray inodes migrated or purged prior to `up:drained` so the journal and stray dir are completely clean.
- **Open File Table (`OpenFileTable`) & InoTables (`InoTable`, `SnapClient`):** Confirm whether `up:draining` must flush and reset/save `InoTable` and `OpenFileTable` identically to `up:stopping`, or if a newly promoted MDS coming into a previously `up:drained` rank takes the `up:starting` path (reading existing root/tables) vs. `up:creating`. Note: The spec states *"Starting with an essentially clean journal, no state, and no client sessions, the new daemon should go back to up:active within a few seconds"*, which corresponds to `up:starting` (`STATE_STARTING`).

---

### Agent 5: QA, Fault Injection, & Performance Validation

#### Scope & Target Files
- `qa/tasks/cephfs/test_mds_drain.py` (new test module)
- `qa/suites/fs/upgrade/` or `qa/suites/fs/basic_functional/`

#### Implementation Steps
1. **Functional Lifecycle Tests (`test_mds_drain.py`):**
   - **Test 1 (Basic Drain & Clear):** Start a multi-MDS cluster (`max_mds = 2` or `3`), create directories with ephemeral pins and unpinned subtrees, drain rank 1, verify transition `up:active` -> `up:draining` -> `MDSMap::drained`, verify no standby is promoted while in `MDSMap::drained`, run `ceph fs clear-drain`, and verify rapid transition to `up:active` (< 5 seconds).
   - **Test 2 (Pin Redistribution & Return):** Verify that ephemerally pinned subtrees on rank 1 migrate to other active ranks during `up:draining`, and non-ephemerally pinned subtrees migrate to rank 0. Verify subtrees migrate back to rank 1 after `ceph fs clear-drain` brings rank 1 back to `up:active`.
   - **Test 3 (Crash Recovery During Drain):** Kill (`SIGKILL`) an `up:draining` MDS daemon mid-drain. Verify that when a standby takes over the rank and finishes replay/rejoin, it enters `up:draining` (not `up:active`) and finishes draining to `up:drained`.
2. **Production Simulation & Load Benchmark Harness:**
   - Create a workload test that continuously runs metadata-intensive operations (file creates, renames, unlinks, stat storms across ephemerally pinned directories) while sequentially draining and clearing ranks in a loop.
   - Record and assert metrics on:
     - Maximum subtree freeze duration (monitoring for extended unavailability).
     - Client request latency percentiles (p50, p95, p99) and metadata request throughput drops during `up:draining` and `up:starting`.

---

## 5. Summary Checklist for Integration Review

- [ ] `MDSMap` encodes/decodes `draining` and `drained` sets cleanly and prints them in status outputs.
- [ ] Ranks in `MDSMap::draining` always enter `up:draining` upon startup/recovery instead of `up:active`.
- [ ] Ephemeral pinning excludes ranks in `draining` and `drained` sets.
- [ ] `up:draining` rank migrates ephemerally pinned subtrees across active ranks and remaining subtrees to `rank 0`, flushes its journal, and sends `up:drained` to Monitors.
- [ ] Monitors move the rank from `MDSMap::draining` to `MDSMap::drained` upon receiving `up:drained` and do not assign any standby until `ceph fs clear-drain` is executed.
- [ ] Replacement MDS reaches `up:active` within seconds on the drained rank and reclaims pinned subtrees.