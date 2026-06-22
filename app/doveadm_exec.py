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
    quoted_folder = folder
    cmd = ['docker', 'exec', '{container}', 'doveadm', action, '-u', mailbox]

    from_key = 'HEADER From' if use_header else 'from'
    unit_map = {'days': 'd', 'weeks': 'w', 'months': 'M', 'years': 'y'}
    age_str = f'{age_value}{unit_map.get(age_unit, "d")}' if age_value is not None and age_unit else None

    if match_or and len(from_addrs) > 1:
        parts = []
        for addr in from_addrs[:-1]:
            parts.append('OR')
            parts.append(from_key)
            parts.append(addr)
        parts.append(from_key)
        parts.append(from_addrs[-1])
    else:
        parts = []
        for addr in from_addrs:
            parts.append(from_key)
            parts.append(addr)

    if subject:
        if len(from_addrs) > 0:
            if match_or:
                pass
            else:
                parts.append('subject')
                parts.append(subject)
        else:
            parts.append('subject')
            parts.append(subject)

    if age_str:
        parts.append('savedbefore')
        parts.append(age_str)

    cmd.extend(['mailbox', quoted_folder])
    cmd.extend(parts)
    return cmd


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

    for folder in folders:
        cmd = _build_cmd('search', mailbox, folder, from_addrs, subject,
                         age_value, age_unit, match_or, use_header)
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

    for folder in folders:
        cmd = _build_cmd('expunge', mailbox, folder, from_addrs, subject,
                         age_value, age_unit, match_or, use_header)
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
    }
