"""Field allowlist for the existing local Java method-index v1 import format.

This rejects payload extensions and malformed containers. It is not a secret or
personal-data detector: trusted producers must supply metadata only.
"""
from pathlib import PurePosixPath
import re

from tools.method_evidence.evidence import BUILD_FIELDS, HEX64

SYMBOL = {"module", "class", "name", "descriptor"}
METHOD = SYMBOL | {"native", "abstract", "hasBody", "reachable", "source", "line"}
LOCATION = {"source", "line", "bytecodeIndex"}


def fields(value, allowed, required=()):
    if not isinstance(value, dict) or not set(required) <= set(value) <= set(allowed):
        raise ValueError("Unknown or missing index fields")
    return value


def text(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 4096 or any(c in value for c in "\0\r\n"):
        raise ValueError("Invalid metadata text")


def sequence(value):
    if not isinstance(value, list):
        raise ValueError("Expected a metadata list")
    return value


def method(value, extended=False):
    fields(value, METHOD if extended else SYMBOL, SYMBOL)
    for key in SYMBOL:
        text(value[key])
    for key in ("native", "abstract", "hasBody", "reachable"):
        if key in value and type(value[key]) is not bool:
            raise ValueError("Invalid method flag")
    location(value)


def location(value):
    for key in ("line", "bytecodeIndex"):
        if key in value and (type(value[key]) is not int or value[key] < -1):
            raise ValueError("Invalid code location")
    if "source" in value:
        path = value["source"]
        text(path)
        if (PurePosixPath(path).is_absolute() or ".." in PurePosixPath(path).parts or
                not re.fullmatch(r"[\w.$/-]+\.java", path)):
            raise ValueError("Expected a relative Java source path, never a source body")


def validate_schema(index):
    top = {"schema", "analysisRunId", "buildIdentity", "configSha256", "config", "input", "provenance",
           "methods", "staticEvidence", "limitations", "identityAssurance", "indexSha256"}
    fields(index, top, top)
    fields(index["buildIdentity"], BUILD_FIELDS, BUILD_FIELDS)
    for value in index["buildIdentity"].values():
        text(value)
    for key in ("schema", "analysisRunId", "configSha256", "identityAssurance", "indexSha256"):
        text(index[key])
    inputs = {"artifactSha256", "classInputSha256", "metadataInputSha256", "sourceTreeSha256"}
    fields(index["input"], inputs)
    for value in index["input"].values():
        if not isinstance(value, str) or not HEX64.fullmatch(value):
            raise ValueError("Invalid input digest")
    provenance = {"adapterVersion", "dependencyMode", "javaVendor", "javaVersion", "maximumBytecodeRelease"}
    fields(index["provenance"], provenance, {"adapterVersion"})
    for key, value in index["provenance"].items():
        if key == "maximumBytecodeRelease":
            if type(value) is not int or not 1 <= value <= 100:
                raise ValueError("Invalid bytecode release")
        else:
            text(value)
    for item in sequence(index["methods"]):
        method(item)
    for item in sequence(index["limitations"]):
        text(item)
    validate_config(index["config"])
    tools = fields(index["staticEvidence"], {"javaparser", "wala"}, {"javaparser", "wala"})
    for tool in tools.values():
        validate_tool(tool)


def validate_config(config):
    fields(config, {"scope", "schema", "adapter", "tools"}, {"schema", "adapter", "tools"})
    text(config["schema"])
    text(config["adapter"])
    if "scope" in config:
        fields(config["scope"], {"includePackage", "excludedPackages"}, {"includePackage"})
        text(config["scope"]["includePackage"])
        for item in sequence(config["scope"].get("excludedPackages", [])):
            text(item)
    fields(config["tools"], {"javaparser", "wala"})
    for tool in config["tools"].values():
        fields(tool, {"version", "algorithm", "entrypoints", "reflectionPolicy"}, {"version"})
        for key, value in tool.items():
            if key == "entrypoints" and value is not None:
                for item in sequence(value):
                    method(item)
            elif value is not None:
                text(value)


def validate_tool(tool):
    allowed = {"version", "kind", "languageLevel", "algorithm", "applicationOnly", "entrypoints",
               "reflectionPolicy", "reachability", "methods", "calls", "unresolved", "excluded"}
    fields(tool, allowed, {"version", "methods", "calls"})
    for key, value in tool.items():
        if key == "applicationOnly":
            if type(value) is not bool:
                raise ValueError("Invalid analyzer flag")
        elif key in {"version", "kind", "languageLevel", "algorithm", "reflectionPolicy", "reachability"}:
            text(value)
    for item in sequence(tool["methods"]):
        method(item, extended=True)
    for item in sequence(tool.get("entrypoints", [])):
        method(item)
    for call in sequence(tool["calls"]):
        fields(call, {"caller", "target", "kind"} | LOCATION, {"caller", "target", "kind"})
        method(call["caller"])
        method(call["target"])
        text(call["kind"])
        location(call)
    for item in sequence(tool.get("unresolved", [])) + sequence(tool.get("excluded", [])):
        fields(item, {"method", "caller", "target", "reason", "failureType"} | LOCATION, {"reason"})
        text(item["reason"])
        if "failureType" in item:
            text(item["failureType"])
        for key in ("method", "caller", "target"):
            if key in item:
                method(item[key])
        location(item)
