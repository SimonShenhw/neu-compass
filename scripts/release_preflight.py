"""Offline, read-only checks of an explicit standalone SQLite copy and archives.

No Settings/.env, network, migrations, exports, or release approval. Exit 0
means only that the requested machine checks passed; manual gates stay pending.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

MAX_DB_BYTES = 512 * 1024 * 1024
MAX_PLAN_FILES = 10
MAX_PLANS = 100
MANUAL_GATES = (
    'credential_rotation', 'target_and_action_authority',
    'consistent_backup_and_restore', 'joint_api_ui_version_and_runtime_config',
    'private_input_deployment_and_index_model_identity', 'retention_and_access_policy',
    'real_account_login_refresh_logout', 'complete_policy_and_personal_pos_review',
    'authorized_distribution',
)
LIMITATIONS = (
    'offline_copy_consistency_is_not_proven',
    'schema_definition_match_is_not_data_or_runtime_acceptance',
    'extra_schema_objects_and_equivalent_ddl_need_human_review',
    'archive_checks_are_not_authenticity_or_complete_policy_or_eligibility',
    'archive_checks_do_not_prove_inputs_imported_into_database',
    'course_requisites_and_retrieval_index_models_not_checked',
    'no_live_configuration_or_real_account_or_retention_verification',
    'aggregate_report_is_not_public_or_anonymized',
)


class PreflightError(Exception):
    """Only fixed internal codes; never wrap a raw exception or input value."""


def _blocked_path(path: Path) -> bool:
    for part in (path, *path.parents):
        if part.is_symlink() or (hasattr(part, 'is_junction') and part.is_junction()):
            return True
    return path.name.lower() == '.env' or path.name.lower().startswith('.env.')


def _existing(path: Path, *, directory: bool = False) -> Path:
    # Refuse UNC/device paths lexically, before a stat could contact a server.
    if str(path).startswith(('\\\\', '//')):
        raise PreflightError('nonlocal_input_path')
    path = Path(path).absolute()
    if _blocked_path(path):
        raise PreflightError('unsafe_input_path')
    path = path.resolve(strict=True)
    if not (path.is_dir() if directory else path.is_file()):
        raise PreflightError('input_kind_mismatch')
    return path


def _digest_file(path: Path, budget: int) -> str:
    if not 0 < path.stat().st_size <= budget:
        raise PreflightError('input_size_budget')
    digest = hashlib.sha256()
    size = 0
    with path.open('rb') as stream:
        while block := stream.read(min(budget + 1 - size, 1024 * 1024)):
            size += len(block)
            if size > budget:
                raise PreflightError('input_size_budget')
            digest.update(block)
    return digest.hexdigest()


class Inputs:
    """Private fingerprints for change detection; paths/hashes are not reported."""

    def __init__(self):
        self.files: dict[Path, tuple[int, str]] = {}

    def track(self, path: Path, budget: int) -> Path:
        path = _existing(path)
        digest = _digest_file(path, budget)
        if path in self.files and self.files[path][1] != digest:
            raise PreflightError('inputs_changed_during_check')
        self.files[path] = (budget, digest)
        return path

    def unchanged(self):
        for path, (budget, digest) in self.files.items():
            if self.track(path, budget) != path or self.files[path][1] != digest:
                raise PreflightError('inputs_changed_during_check')


def _pairs_unique(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise PreflightError('duplicate_json_keys')
        value[key] = item
    return value


def _read_json(inputs: Inputs, path: Path, budget: int):
    path = inputs.track(path, budget)
    with path.open('rb') as stream:
        raw = stream.read(budget + 1)
    if len(raw) > budget:
        raise PreflightError('input_size_budget')
    if hashlib.sha256(raw).hexdigest() != inputs.files[path][1]:
        raise PreflightError('inputs_changed_during_check')
    return json.loads(raw.decode('utf-8-sig'), object_pairs_hook=_pairs_unique,
                      parse_constant=_invalid_number)


def _invalid_number(_):
    raise PreflightError('invalid_json_number')


def _canonical_sql(sql: str) -> tuple[str, ...]:
    # Keep quoted literals intact; only unquoted case/whitespace/comments vary.
    # 中文：不是通用 SQL 等价证明；结构差异失败后由人工判断，绝不自动改表。
    pattern = r"'(?:''|[^'])*'|\"(?:\"\"|[^\"])*\"|`(?:``|[^`])*`|\[[^\]]*\]|--[^\n]*|/\*[\s\S]*?\*/|[a-zA-Z_][a-zA-Z_0-9]*|[^\s]"
    tokens = [token if token[:1] in "'\"`[" else token.lower()
              for token in re.findall(pattern, sql)
              if not token.startswith(('--', '/*'))]
    if tokens[:2] in (['create', 'table'], ['create', 'index'], ['create', 'view'], ['create', 'trigger']):
        if tokens[2:5] == ['if', 'not', 'exists']:
            del tokens[2:5]
    elif tokens[:3] == ['create', 'unique', 'index'] and tokens[3:6] == ['if', 'not', 'exists']:
        del tokens[3:6]
    return tuple(tokens)


def _schema(conn):
    rows = conn.execute("SELECT type, name, sql FROM sqlite_master WHERE name NOT GLOB 'sqlite_*'").fetchmany(1001)
    if len(rows) > 1000 or any(sql is None or len(sql) > 128_000 for _, _, sql in rows):
        raise PreflightError('schema_size_budget')
    return {(kind, name): _canonical_sql(sql) for kind, name, sql in rows}


def _sidecars_absent(path):
    if any(Path(str(path) + suffix).exists() or Path(str(path) + suffix).is_symlink()
           for suffix in ('-wal', '-shm', '-journal')):
        raise PreflightError('offline_copy_sidecars_present')


def _result(name, status, code, **facts):
    return dict(name=name, status=status, code=code, facts=facts)


def _safe_check(report, name, function):
    try:
        facts = function() or {}
        report['checks'].append(_result(name, 'passed', 'checked', **facts))
        return True
    except PreflightError as exc:
        report['checks'].append(_result(name, 'failed', exc.args[0]))
    except Exception:
        # Validation/SQLite/parser exceptions can contain private values.
        report['checks'].append(_result(name, 'failed', 'check_failed'))
    return False


def _database_checks(report, db_copy: Path, inputs: Inputs):
    state = {}

    def prepare():
        path = _existing(db_copy)
        _sidecars_absent(path)
        state['path'] = inputs.track(path, MAX_DB_BYTES)
        return {'standalone_sidecars_absent': True}

    names = ('database_integrity', 'schema_contract', 'schema_versions', 'foreign_keys')
    if not _safe_check(report, 'database_copy', prepare):
        report['checks'].extend(_result(name, 'not_checked', 'database_copy_unavailable') for name in names)
        return
    conn = reference = None
    try:
        # immutable avoids creating shm/wal; valid only for a stable offline copy.
        conn = sqlite3.connect(state['path'].as_uri() + '?mode=ro&immutable=1', uri=True, timeout=1)
        conn.execute('PRAGMA query_only=ON')
        conn.execute('PRAGMA trusted_schema=OFF')
        deadline, steps = time.monotonic() + 10, 0

        def bounded():
            nonlocal steps
            steps += 10_000
            return int(steps > 50_000_000 or time.monotonic() > deadline)

        conn.set_progress_handler(bounded, 10_000)
        conn.execute('BEGIN')

        def integrity():
            if conn.execute('PRAGMA quick_check(1)').fetchone() != ('ok',):
                raise PreflightError('database_integrity_failed')

        _safe_check(report, 'database_integrity', integrity)

        def contract():
            nonlocal reference
            schema_file = inputs.track(ROOT / 'db/init.sql', 128_000)
            reference = sqlite3.connect(':memory:')
            reference.executescript(schema_file.read_text(encoding='utf-8-sig'))
            expected, actual = _schema(reference), _schema(conn)
            missing = set(expected) - set(actual)
            mismatched = [key for key in expected.keys() & actual.keys() if expected[key] != actual[key]]
            if missing or mismatched:
                raise PreflightError('schema_definition_mismatch')
            return {'required_objects_matched': len(expected),
                    'extra_objects_not_reviewed': len(set(actual) - set(expected))}

        _safe_check(report, 'schema_contract', contract)

        def versions():
            versions = tuple(f'1.{number}' for number in range(8))
            found = {row[0] for row in conn.execute(
                "SELECT version FROM schema_versions WHERE version IN (?,?,?,?,?,?,?,?)", versions)}
            if found != set(versions):
                raise PreflightError('required_schema_versions_missing')
            return {'required_versions_present': len(versions)}

        _safe_check(report, 'schema_versions', versions)

        def foreign_keys():
            if conn.execute('PRAGMA foreign_key_check').fetchone() is not None:
                raise PreflightError('foreign_key_violation')

        _safe_check(report, 'foreign_keys', foreign_keys)
        _sidecars_absent(state['path'])
    except Exception:
        report['checks'].append(_result('database_snapshot', 'failed', 'database_snapshot_check_failed'))
    finally:
        if conn is not None:
            conn.close()
        if reference is not None:
            reference.close()


def _archive(inputs: Inputs, directory: Path, fingerprint: str):
    inputs.track(directory / (fingerprint + '.html'), 2_000_000)
    _read_json(inputs, directory / (fingerprint + '.json'), 16_000)


def _source_checks(report, inputs, plan_files, program_source_dir, policy_bundle, policy_source_dir):
    plans, paths = [], []

    def plan_check():
        # These domain/audit modules do not import Settings or use network clients.
        from schemas.program_plan import ProgramPlan
        from scripts.audit_program_rule_sources import audit_plan

        if not plan_files or not program_source_dir or not 1 <= len(plan_files) <= MAX_PLAN_FILES:
            raise PreflightError('plan_input_group_incomplete')
        directory = _existing(program_source_dir, directory=True)
        for path in plan_files:
            data = _read_json(inputs, path, 1_000_000)
            if not isinstance(data, list) or not 1 <= len(data) <= MAX_PLANS:
                raise PreflightError('plan_count_budget')
            paths.append(_existing(path))
            plans.extend(ProgramPlan.model_validate(item) for item in data)
        if (len(set(paths)) != len(paths) or len(plans) > MAX_PLANS
                or len({plan.plan_id for plan in plans}) != len(plans)
                or len({(p.program_id, p.campus, p.catalog_year, p.pathway, p.concentration or '')
                        for p in plans}) != len(plans)):
            raise PreflightError('duplicate_or_excess_plan_scope')
        for plan in plans:
            if plan.campus != 'boston' or plan.catalog_year != '2026-2027':
                raise PreflightError('unsupported_frozen_plan_scope')
            if not plan.source_html_sha256:
                raise PreflightError('plan_source_fingerprint_missing')
            _archive(inputs, directory, plan.source_html_sha256)
            audit_plan(plan, directory)
        return {'plans_checked': len(plans), 'partial_plans': sum(p.coverage == 'partial' for p in plans)}

    if plan_files or program_source_dir:
        plans_ok = _safe_check(report, 'plan_sources', plan_check)
    else:
        plans_ok = False
        report['checks'].append(_result('plan_sources', 'not_checked', 'inputs_not_supplied'))

    def policy_check():
        from schemas.program_policy import ProgramPolicyBundle
        from scripts.audit_program_policy_sources import audit_bundle

        if not policy_bundle or not policy_source_dir:
            raise PreflightError('policy_input_group_incomplete')
        if not plans_ok:
            raise PreflightError('checked_plan_inputs_required')
        directory = _existing(policy_source_dir, directory=True)
        bundle = ProgramPolicyBundle.model_validate(_read_json(inputs, policy_bundle, 300_000))
        for policy in bundle.policies:
            _archive(inputs, directory, policy.source.sha256)
        # Reuse the exact source positions, hash, scope and home-college checks;
        # never expose its detailed source-text report or exception messages.
        audit_bundle(_existing(policy_bundle), paths, directory, _existing(program_source_dir, directory=True))
        linked = {link.plan_id for link in bundle.links}
        unlinked = len({plan.plan_id for plan in plans} - linked)
        if unlinked:
            raise PreflightError('selected_plans_missing_policy_links')
        return {'policy_pages_checked': len(bundle.policies), 'plan_links_checked': len(bundle.links),
                'selected_fragments_only': True}

    if policy_bundle or policy_source_dir:
        _safe_check(report, 'policy_sources', policy_check)
    else:
        report['checks'].append(_result('policy_sources', 'not_checked', 'inputs_not_supplied'))


def run_preflight(db_copy: Path, *, plan_files=(), program_source_dir=None,
                  policy_bundle=None, policy_source_dir=None) -> dict:
    report = dict(format_version=1, machine_status='failed', release_approved=False,
                  checks=[], manual_gates=[dict(name=name, status='pending') for name in MANUAL_GATES],
                  limitations=list(LIMITATIONS))
    inputs = Inputs()
    _database_checks(report, db_copy, inputs)
    _source_checks(report, inputs, plan_files, program_source_dir, policy_bundle, policy_source_dir)
    def stable():
        inputs.unchanged()
        if any(item['name'] == 'database_copy' and item['status'] == 'passed' for item in report['checks']):
            _sidecars_absent(_existing(db_copy))

    _safe_check(report, 'input_stability', stable)
    if not any(item['status'] == 'failed' for item in report['checks']):
        report['machine_status'] = 'requested_checks_passed'
    return report


class SafeParser(argparse.ArgumentParser):
    def error(self, message):
        # argparse's normal errors echo unknown arguments, including secrets.
        print(json.dumps({'format_version': 1, 'machine_status': 'failed',
                          'release_approved': False, 'code': 'invalid_arguments'}))
        raise SystemExit(2)


def cli(argv=None) -> int:
    parser = SafeParser(description=__doc__)
    parser.add_argument('--db-copy', required=True, type=Path)
    parser.add_argument('--plan-file', action='append', type=Path, default=[])
    parser.add_argument('--program-source-dir', type=Path)
    parser.add_argument('--policy-bundle', type=Path)
    parser.add_argument('--policy-source-dir', type=Path)
    args = parser.parse_args(argv)
    try:
        report = run_preflight(args.db_copy, plan_files=args.plan_file,
            program_source_dir=args.program_source_dir, policy_bundle=args.policy_bundle,
            policy_source_dir=args.policy_source_dir)
        print(json.dumps(report, ensure_ascii=True, sort_keys=True))
        return 0 if report['machine_status'] == 'requested_checks_passed' else 1
    except Exception:
        print(json.dumps({'format_version': 1, 'machine_status': 'failed',
                          'release_approved': False, 'code': 'preflight_failed'}))
        return 1


if __name__ == '__main__':
    raise SystemExit(cli())
