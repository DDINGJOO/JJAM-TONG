# OSS 조사 출처·릴리스 스냅샷

조사일: 2026-11-12. [아키텍처 비교](OSS-ARCHITECTURE-COMPARISON.md)를 뒷받침하는 **릴리스 메타데이터와 해당 tag의 라이선스 원문 확인 기록**이다. 제품 채택·실행 호환성·성능·보안 검증 결과가 아니다.

GitHub 공개 API의 `releases/latest`와 반환된 tag의 `license`를 조회했다. 이는 저장소가 latest로 지정한 릴리스이며 모든 채널·장기지원 버전 중 권장 버전을 뜻하지 않는다. 실제 호환 조합은 별도 고정한다. 기계 판독용 값과 조회 시각·라이선스 본문 SHA-256은 [JSON 기록](oss-source-snapshot.json)에 있다.

| 대상 | 확인한 릴리스 | 발행일 UTC | 해당 버전 라이선스 원문·표기 |
| --- | --- | --- | --- |
| Backstage | [v1.56.4](https://github.com/backstage/backstage/releases/tag/v1.56.4) | 2026-11-09 | [Apache-2.0](https://github.com/backstage/backstage/blob/v1.56.4/LICENSE) |
| OpenChoreo | [v1.3.3](https://github.com/openchoreo/openchoreo/releases/tag/v1.3.3) | 2026-10-29 | [Apache-2.0](https://github.com/openchoreo/openchoreo/blob/v1.3.3/LICENSE) |
| OTel Collector core | [v0.165.0](https://github.com/open-telemetry/opentelemetry-collector/releases/tag/v0.165.0) | 2026-11-06 | [Apache-2.0](https://github.com/open-telemetry/opentelemetry-collector/blob/v0.165.0/LICENSE) |
| OTel Collector contrib | [v0.165.1](https://github.com/open-telemetry/opentelemetry-collector-contrib/releases/tag/v0.165.1) | 2026-11-09 | [Apache-2.0](https://github.com/open-telemetry/opentelemetry-collector-contrib/blob/v0.165.1/LICENSE) |
| OTel Java instrumentation | [v2.33.1](https://github.com/open-telemetry/opentelemetry-java-instrumentation/releases/tag/v2.33.1) | 2026-10-26 | [Apache-2.0](https://github.com/open-telemetry/opentelemetry-java-instrumentation/blob/v2.33.1/LICENSE) |
| SkyWalking core | [v11.1.0](https://github.com/apache/skywalking/releases/tag/v11.1.0) | 2026-11-06 | [Apache-2.0](https://github.com/apache/skywalking/blob/v11.1.0/LICENSE) |
| SootUp | [v3.0.1](https://github.com/soot-oss/SootUp/releases/tag/v3.0.1) | 2026-08-07 | [LGPL-2.1](https://github.com/soot-oss/SootUp/blob/v3.0.1/LICENSE) |
| Cartography | [0.144.0](https://github.com/cartography-cncf/cartography/releases/tag/0.144.0) | 2026-10-29 | [Apache-2.0](https://github.com/cartography-cncf/cartography/blob/0.144.0/LICENSE) |
| NetBox core | [v4.7.5](https://github.com/netbox-community/netbox/releases/tag/v4.7.5) | 2026-11-10 | [Apache-2.0](https://github.com/netbox-community/netbox/blob/v4.7.5/LICENSE.txt) |
| Crossplane core | [v2.4.3](https://github.com/crossplane/crossplane/releases/tag/v2.4.3) | 2026-10-22 | [Apache-2.0](https://github.com/crossplane/crossplane/blob/v2.4.3/LICENSE) |
| Flux distribution | [v2.10.0](https://github.com/fluxcd/flux2/releases/tag/v2.10.0) | 2026-10-26 | [Apache-2.0](https://github.com/fluxcd/flux2/blob/v2.10.0/LICENSE) |
| Wazuh server/agent repository | [v4.14.10](https://github.com/wazuh/wazuh/releases/tag/v4.14.10) | 2026-11-09 | [GPL v2 표기 및 예외·별도 조항; API는 NOASSERTION](https://github.com/wazuh/wazuh/blob/v4.14.10/LICENSE) |
| Falco core | [0.45.2](https://github.com/falcosecurity/falco/releases/tag/0.45.2) | 2026-10-29 | [Apache-2.0](https://github.com/falcosecurity/falco/blob/0.45.2/LICENSE) |
| Pyroscope server | [v2.4.3](https://github.com/grafana/pyroscope/releases/tag/v2.4.3) | 2026-11-03 | [AGPL-3.0](https://github.com/grafana/pyroscope/blob/v2.4.3/LICENSE) |
| AppMap Java (별도 참고) | [v1.30.2](https://github.com/getappmap/appmap-java/releases/tag/v1.30.2) | 2026-09-18 | [MIT + Commons Clause; API는 NOASSERTION](https://github.com/getappmap/appmap-java/blob/v1.30.2/LICENSE.txt) |

## 읽는 방법과 미확인 항목

- 12개 OSS 계열의 구조를 비교했고 관련 14개 OSS 저장소와 별도 참고 AppMap Java 1개, 총 15개 저장소의 메타데이터를 기록했다. 코드·라이선스를 JJAM-TONG에 복사하거나 의존성을 설치하지 않았다.
- Apache-2.0 등의 표기는 해당 저장소·버전에 한정한다. 배포판·plugin·provider·driver·SDK·transitive dependency의 라이선스와 NOTICE는 따로 확인한다. API 판정이 NOASSERTION인 Wazuh와 AppMap은 원문을 읽고 표기를 보완했다.
- Collector core와 contrib는 별도 저장소다. `file_storage` 같은 contrib 구성요소가 core 배포판에 모두 포함된다고 가정하지 않는다. 배포판 manifest·각 component의 안정성·호환 버전은 PoC에서 고정한다.
- SkyWalking core 버전은 각 언어 agent와 storage 버전의 호환 검증을 대신하지 않는다. Crossplane core의 Apache-2.0은 별도 provider·function의 라이선스·managementPolicies 지원을 보증하지 않는다.
- Wazuh 표기는 위 repository에 한정한다. indexer·dashboard·연계 도구의 라이선스를 하나로 묶지 않는다. Pyroscope server의 AGPL 표기를 각 언어 SDK의 라이선스로 옮기지 않는다.
- AppMap Java의 추가 Commons Clause를 단순 MIT로 생략하지 않는다. 일반 OSS 재사용 후보와 분리한 구조 참고 사례다.
- 최신 문서는 변경될 수 있고 일부 기능은 확인한 릴리스와 다를 수 있다. 재현할 때 release/commit·artifact digest·설정·SDK/provider·문서 revision을 함께 남긴다. tag도 변경될 수 있으므로 실제 도입 시 commit과 배포 artifact까지 고정한다.
- 최근 릴리스 날짜만으로 유지보수 품질·장기 지원·보안·안정성을 평가하지 않는다. 릴리스 노트의 breaking change, 미해결 issue, 보안 advisory/CVE, SBOM, 배포·수정 방식의 조건과 실제 운영 비용은 미검증이다.
- SHA-256은 이번에 읽은 라이선스 원문을 식별하며 제품 binary의 공급망 서명이나 법률 검토를 대신하지 않는다.
