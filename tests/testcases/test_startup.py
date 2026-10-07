import subprocess

import backend.startup as startup


def test_nvidia_detection_prefers_nvidia_smi(monkeypatch):
    calls = []

    def check_output(command, **_kwargs):
        calls.append(command)
        return b'NVIDIA GeForce RTX 3080\r\n'

    monkeypatch.setattr(startup.subprocess, 'check_output', check_output)

    assert startup.is_nvidia_gpu_present() is True
    assert calls == [[
        'nvidia-smi',
        '--query-gpu=name',
        '--format=csv,noheader',
    ]]
    assert startup.guess_torch_url() == startup.WHEEL_URLS['torch==1.10.1+cu113']


def test_nvidia_detection_uses_powershell_when_wmic_is_unavailable(monkeypatch):
    calls = []

    def check_output(command, **_kwargs):
        calls.append(command)
        if command[0] == 'nvidia-smi':
            raise OSError('nvidia-smi is not on PATH')
        return b'NVIDIA GeForce RTX 3080\r\n'

    monkeypatch.setattr(startup.subprocess, 'check_output', check_output)

    assert startup.is_nvidia_gpu_present() is True
    assert [command[0] for command in calls] == ['nvidia-smi', 'powershell']


def test_nvidia_detection_falls_back_to_cpu_when_probes_fail(monkeypatch):
    def check_output(_command, **_kwargs):
        raise subprocess.CalledProcessError(1, 'probe')

    monkeypatch.setattr(startup.subprocess, 'check_output', check_output)

    assert startup.is_nvidia_gpu_present() is False
    assert startup.guess_torch_url() == startup.WHEEL_URLS['torch==1.10.1+cpu']
