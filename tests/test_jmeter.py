"""Unit tests for JMeter JMX parser."""

from __future__ import annotations

from pathlib import Path

import pytest

from deli.exceptions import DeliCollectionError
from deli.jmeter import load_jmx, load_jmx_run_config, unresolved_variables_in_requests


def _write_jmx(path: Path) -> None:
    path.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<jmeterTestPlan version="1.2" properties="5.0" jmeter="5.6.3">
  <hashTree>
    <TestPlan testname="Plan">
      <elementProp name="TestPlan.user_defined_variables" elementType="Arguments">
        <collectionProp name="Arguments.arguments">
          <elementProp name="host" elementType="Argument">
            <stringProp name="Argument.name">host</stringProp>
            <stringProp name="Argument.value">api.example.com</stringProp>
          </elementProp>
        </collectionProp>
      </elementProp>
    </TestPlan>
    <hashTree>
      <ThreadGroup testname="Thread Group"/>
      <hashTree>
        <ConfigTestElement testname="HTTP Request Defaults">
          <stringProp name="HTTPSampler.protocol">https</stringProp>
          <stringProp name="HTTPSampler.domain">${host}</stringProp>
        </ConfigTestElement>
        <hashTree/>
        <HeaderManager testname="HTTP Header Manager">
          <collectionProp name="HeaderManager.headers">
            <elementProp name="" elementType="Header">
              <stringProp name="Header.name">X-Test</stringProp>
              <stringProp name="Header.value">${token}</stringProp>
            </elementProp>
          </collectionProp>
        </HeaderManager>
        <hashTree/>
        <HTTPSamplerProxy testname="Search">
          <stringProp name="HTTPSampler.path">/search</stringProp>
          <stringProp name="HTTPSampler.method">GET</stringProp>
          <elementProp name="HTTPsampler.Arguments" elementType="Arguments">
            <collectionProp name="Arguments.arguments">
              <elementProp name="q" elementType="HTTPArgument">
                <stringProp name="Argument.name">q</stringProp>
                <stringProp name="Argument.value">mavi jeans</stringProp>
              </elementProp>
            </collectionProp>
          </elementProp>
        </HTTPSamplerProxy>
        <hashTree/>
        <HTTPSamplerProxy testname="Create">
          <stringProp name="HTTPSampler.path">/users</stringProp>
          <stringProp name="HTTPSampler.method">POST</stringProp>
          <elementProp name="HTTPsampler.Arguments" elementType="Arguments">
            <collectionProp name="Arguments.arguments">
              <elementProp name="name" elementType="HTTPArgument">
                <stringProp name="Argument.name">name</stringProp>
                <stringProp name="Argument.value">${username}</stringProp>
              </elementProp>
            </collectionProp>
          </elementProp>
        </HTTPSamplerProxy>
        <hashTree/>
      </hashTree>
    </hashTree>
  </hashTree>
</jmeterTestPlan>
""",
        encoding="utf-8",
    )


def test_load_jmx_http_samplers_with_variables_and_overrides(tmp_path: Path) -> None:
    jmx = tmp_path / "plan.jmx"
    _write_jmx(jmx)

    requests = load_jmx(
        jmx,
        env_override={"token": "abc", "username": "alice", "host": "override.example.com"},
    )

    assert len(requests) == 2
    assert requests[0].name == "Search"
    assert requests[0].method == "GET"
    assert requests[0].url == "https://override.example.com/search?q=mavi+jeans"
    assert requests[0].headers["X-Test"] == "abc"
    assert requests[1].name == "Create"
    assert requests[1].method == "POST"
    assert requests[1].url == "https://override.example.com/users"
    assert requests[1].body == "name=alice"
    assert requests[1].headers["Content-Type"] == "application/x-www-form-urlencoded"


def test_load_jmx_reports_unresolved_variables(tmp_path: Path) -> None:
    jmx = tmp_path / "plan.jmx"
    _write_jmx(jmx)

    requests = load_jmx(jmx, env_override={"token": "abc"})

    assert unresolved_variables_in_requests(requests) == {"Create": ["username"]}


def test_load_jmx_file_not_found() -> None:
    with pytest.raises(DeliCollectionError, match="JMeter JMX file not found"):
        load_jmx("/missing/plan.jmx")


def test_load_jmx_invalid_xml(tmp_path: Path) -> None:
    jmx = tmp_path / "bad.jmx"
    jmx.write_text("<jmeterTestPlan>", encoding="utf-8")

    with pytest.raises(DeliCollectionError, match="Invalid JMeter JMX XML"):
        load_jmx(jmx)


def test_load_jmx_run_config_from_thread_group(tmp_path: Path) -> None:
    jmx = tmp_path / "threadgroup.jmx"
    jmx.write_text(
        """<jmeterTestPlan>
          <hashTree>
            <TestPlan testname="Plan"/>
            <hashTree>
              <ThreadGroup testname="Thread Group">
                <stringProp name="ThreadGroup.num_threads">${users}</stringProp>
                <stringProp name="ThreadGroup.ramp_time">3</stringProp>
                <stringProp name="ThreadGroup.duration">20</stringProp>
                <elementProp name="ThreadGroup.main_controller" elementType="LoopController">
                  <boolProp name="LoopController.continue_forever">false</boolProp>
                  <stringProp name="LoopController.loops">2</stringProp>
                </elementProp>
              </ThreadGroup>
              <hashTree/>
            </hashTree>
          </hashTree>
        </jmeterTestPlan>""",
        encoding="utf-8",
    )

    config = load_jmx_run_config(jmx, env_override={"users": "7"})

    assert config.users == 7
    assert config.ramp_up_seconds == 3
    assert config.duration_seconds == 20
    assert config.iterations == 2
