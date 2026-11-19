.PHONY: fmt # format codebase
fmt:
	uvx isort .
	uvx autoflake --remove-all-unused-imports --recursive --in-place .
	uvx ruff format --config line-length=500 .

.PHONY: sec # check for vulns
sec:
	uvx bandit -r .

.PHONY: help # generate help message
help:
	@printf "Usage: make [target]\n\n"
	@grep '^.PHONY: .* #' makefile | sed 's/\.PHONY: \(.*\) # \(.*\)/\1	\2/' | expand -t20
