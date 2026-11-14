.PHONY: test run serve verify clean

test:
	python -m pytest -q

run:
	python -m sample_attest run --plan plans/stratified_basic.yaml --out out/

serve:
	python -m sample_attest serve

verify:
	python -m sample_attest verify --plan plans/stratified_basic.yaml

clean:
	rm -rf out .sample_attest .pytest_cache .coverage
