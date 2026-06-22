import subprocess
import shlex


def _foldername(folder: str) -> str:
    return folder


def _build_cmd(
    action: str,
    mailbox: str,
    folder: str,
    from_addrs: list[str],
    subject: str | None,
    age_value: int | None,
    age_unit: str | None,
    match_or: bool,
    use_header: bool,
) -> list[str]:
    cmd = ['docker', 'exec', '{container}', 'doveadm', action, '-u', mailbox]

    from_key = 'HEADER From' if use_header else 'from'
    unit_map = {'days': 'd', 'weeks': 'w', 'months': 'M', 'years': 'y'}
    age_str = f'{age_value}{unit_map.get(age_unit, "d")}' if age_value is not None and age_unit else None

    conditions = []

    for addr in from_addrs:
        conditions.append((from_key, addr))

    if subject:
        conditions.append(('subject', subject))

    if age_str:
        conditions.append(('savedbefore', age_str))

    parts = _build_doveadm_query(conditions, match_or)

    cmd.extend(['mailbox', folder])
    cmd.extend(parts)
    return cmd


def _build_doveadm_query(conditions: list[tuple[str, str]], use_or: bool) -> list[str]:
    if not conditions:
        return []

    if len(conditions) == 1:
        key, val = conditions[0]
        return [key, val]

    if use_or:
        result = []
        for key, val in conditions[:-1]:
            result.append('OR')
            result.append(key)
            result.append(val)
        result.append(conditions[-1][0])
        result.append(conditions[-1][1])
        return result
    else:
        result = []
        for key, val in conditions:
            result.append(key)
            result.append(val)
        return result


def _run(cmd_template, container: str, timeout: int = 120) -> subprocess.CompletedProcess:
    cmd = [c.replace('{container}', container) if '{container}' in c else c for c in cmd_template]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def preview(
    mailbox: str,
    folders: list[str],
    from_addrs: list[str],
    subject: str | None = None,
    age_value: int | None = None,
    age_unit: str | None = None,
    match_or: bool = False,
    use_header: bool = False,
    dovecot_container: str = 'dovecot-mailcow',
) -> dict:
    total = 0
    per_folder = {}
    errors = []
    commands_run = []

    for folder in folders:
        cmd = _build_cmd('search', mailbox, folder, from_addrs, subject,
                         age_value, age_unit, match_or, use_header)
        resolved = [c.replace('{container}', dovecot_container) if '{container}' in c else c for c in cmd]
        commands_run.append(' '.join(shlex.quote(c) for c in resolved))
        try:
            result = _run(cmd, dovecot_container)
            if result.returncode == 0:
                count = len([l for l in result.stdout.strip().split('\n') if l.strip()])
                per_folder[folder] = count
                total += count
            else:
                err = result.stderr.strip() or 'Unknown error'
                per_folder[folder] = -1
                errors.append(f'{folder}: {err}')
        except subprocess.TimeoutExpired:
            per_folder[folder] = -1
            errors.append(f'{folder}: timed out')
        except FileNotFoundError:
            return {'error': 'Docker CLI not found. Install docker CLI in the container.', 'success': False}
        except Exception as e:
            per_folder[folder] = -1
            errors.append(f'{folder}: {str(e)}')

    return {
        'success': len(errors) == 0,
        'total': total,
        'per_folder': per_folder,
        'errors': errors,
        'commands': commands_run,
    }


def execute(
    mailbox: str,
    folders: list[str],
    from_addrs: list[str],
    subject: str | None = None,
    age_value: int | None = None,
    age_unit: str | None = None,
    match_or: bool = False,
    use_header: bool = False,
    dovecot_container: str = 'dovecot-mailcow',
) -> dict:
    deleted = 0
    per_folder = {}
    errors = []
    commands_run = []

    for folder in folders:
        cmd = _build_cmd('expunge', mailbox, folder, from_addrs, subject,
                         age_value, age_unit, match_or, use_header)
        resolved = [c.replace('{container}', dovecot_container) if '{container}' in c else c for c in cmd]
        commands_run.append(' '.join(shlex.quote(c) for c in resolved))
        try:
            result = _run(cmd, dovecot_container)
            if result.returncode == 0:
                per_folder[folder] = True
            else:
                err = result.stderr.strip() or 'Unknown error'
                per_folder[folder] = False
                errors.append(f'{folder}: {err}')
        except subprocess.TimeoutExpired:
            per_folder[folder] = False
            errors.append(f'{folder}: timed out')
        except FileNotFoundError:
            return {'error': 'Docker CLI not found.', 'success': False}
        except Exception as e:
            per_folder[folder] = False
            errors.append(f'{folder}: {str(e)}')

    return {
        'success': len(errors) == 0,
        'deleted': deleted,
        'per_folder': per_folder,
        'errors': errors,
        'commands': commands_run,
    }
