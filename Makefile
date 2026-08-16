.PHONY: fmt lint type test ci-local

fmt:
	poetry run task fmt

lint:
	poetry run task lint_check

type:
	poetry run task type_check

test:
	poetry run task test

ci-local:
	poetry run task ci_local

