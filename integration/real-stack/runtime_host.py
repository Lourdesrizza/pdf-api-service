"""Host controller; targets only the supplied harness project/container."""
import argparse
import hashlib
import json
import subprocess
import time
from pathlib import Path


def run():
    parser = argparse.ArgumentParser()
    parser.add_argument('metadata')
    args = parser.parse_args()
    metadata = json.loads(Path(args.metadata).read_text(encoding='utf-8-sig'))
    project = metadata['project']
    if project != 'pdf-api-real-' + metadata['runId']:
        raise RuntimeError('Unexpected test project')
    directory = Path(__file__).resolve().parent
    compose = ['docker', 'compose', '-p', project, '-f', str(directory / 'compose.yaml')]
    def check(*arguments):
        return subprocess.check_output(arguments, text=True).strip()
    container = check(*compose, 'ps', '-q', 'api')
    if check('docker', 'inspect', '-f', '{{index .Config.Labels "com.docker.compose.project"}}', container) != project:
        raise RuntimeError('Container ownership mismatch')
    inspect = json.loads(check('docker', 'inspect', container))[0]
    assert inspect['HostConfig']['Memory'] == 512 * 1024**2
    assert inspect['HostConfig']['NanoCpus'] == 1_000_000_000
    assert inspect['Config']['User'] == 'app'
    source_code = "import pathlib,hashlib,json; print(json.dumps({str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in pathlib.Path('app').rglob('*.py')}))"
    image_sources = json.loads(check('docker', 'exec', container, 'python', '-c', source_code))
    api_root = Path(metadata['apiRepoPath'])
    local_sources = {str(p.relative_to(api_root)).replace('\\', '/'): hashlib.sha256(p.read_bytes()).hexdigest()
                     for p in (api_root / 'app').rglob('*.py')}
    assert image_sources == local_sources, 'Running image differs from current app source'
    client = [*compose, '--profile', 'client', 'run', '--rm', '-T', '--entrypoint', 'python', 'client', '/tmp/runtime_probe.py']
    with subprocess.Popen([*client, 'load'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) as process:
        samples = []
        while process.poll() is None:
            samples.append(json.loads(check('docker', 'stats', '--no-stream', '--format', '{{json .}}', container)))
            time.sleep(.2)
        stdout, stderr = process.communicate(timeout=15)
        assert process.returncode == 0, stderr
    load = json.loads(stdout)
    peak = int(check('docker', 'exec', container, 'python', '-c',
                     "print(open('/sys/fs/cgroup/memory.peak').read().strip())"))
    with subprocess.Popen([*client, 'shutdown'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) as process:
        marker = process.stdout.readline().strip()
        assert marker == 'INFLIGHT', marker
        subprocess.run(['docker', 'update', '--restart=no', container], check=True, capture_output=True)
        start = time.perf_counter()
        subprocess.run(['docker', 'kill', '--signal', 'TERM', container], check=True, capture_output=True)
        stdout, stderr = process.communicate(timeout=25)
        assert process.returncode == 0, stderr
        exit_code = check('docker', 'wait', container)
        assert exit_code in ('0', '143'), exit_code
        shutdown_logs = subprocess.check_output(['docker', 'logs', container], stderr=subprocess.STDOUT, text=True)
        assert 'Application shutdown complete.' in shutdown_logs
        assert 'Finished server process' in shutdown_logs
        shutdown = {'exit_code': int(exit_code), 'elapsed_seconds': round(time.perf_counter()-start, 3),
                    'response': json.loads(stdout), 'application_shutdown_complete': True}
    logs = check('docker', 'logs', container)
    assert 'SECRET' not in logs
    result = {'project': project, 'api_image_id': inspect['Image'], 'cpu_limit': 1,
              'memory_limit_bytes': 512 * 1024**2, 'load': load,
              'memory_peak_bytes_before_shutdown': peak,
              'app_source_sha256': image_sources,
              'docker_stats_samples': samples, 'sigterm_inflight': shutdown}
    (Path(metadata['runDirectory']) / 'runtime-check.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    subprocess.run([*compose, 'start', 'api'], check=True)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    run()
