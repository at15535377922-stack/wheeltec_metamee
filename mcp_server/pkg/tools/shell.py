import subprocess


class ExecuteShellScript:
    run_args = {
        "shell": {"type": "string", "description": "script to execute"},
        "timeout": {"type": "number", "description": "script execute time"},
    }

    # 定义一些工具
    @staticmethod
    def run(shell: str, timeout: float = 10.0) -> dict:
        """execute shell script,return stdout if return code is zero, if timeout is not passed,then default 10
        Args:
            shell: the shell script
            timeout: timeout to execute
        """

        result = subprocess.run(
            shell, shell=True, capture_output=True, timeout=int(timeout)
        )
        if result.returncode != 0:
            raise ValueError(
                f"execute shell return {result.returncode},stdout: [{result.stdout}],stderr: [{result.stderr}]"
            )
        return str(result.stdout)
