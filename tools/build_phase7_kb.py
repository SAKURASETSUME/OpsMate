"""离线生成已人工整理的 Phase 7 知识库；不下载、不执行示例命令。"""
from __future__ import annotations
import json
from pathlib import Path
import yaml

# 推荐配置模板：可直接复制使用的起步配置；保留地址与口令均为占位符，需替换后使用。
TEMPLATES: dict[str, list[dict]] = {
    "keepalived": [{
        "name": "主备双节点模板（MASTER/BACKUP）",
        "desc": "VRRP 主备 + 后端健康检查脚本；备节点只需改 state/priority 两处。",
        "content": """global_defs {
    router_id LB_01
    vrrp_skip_check_adv_addr
    enable_script_security
    script_user keepalived_script
}

vrrp_script chk_service {
    script "/usr/local/bin/check_service.sh"
    interval 2
    timeout 1
    weight -30
    fall 2
    rise 2
}

vrrp_instance VI_1 {
    # 主节点 state MASTER / priority 100；备节点改为 state BACKUP / priority 90
    state MASTER
    interface eth0
    virtual_router_id 51
    priority 100
    advert_int 1
    authentication {
        auth_type PASS
        auth_pass example
    }
    virtual_ipaddress {
        192.0.2.100/24 dev eth0
    }
    track_script {
        chk_service
    }
    notify_master "/usr/local/bin/notify.sh master"
    notify_backup "/usr/local/bin/notify.sh backup"
}
"""}],
    "kafka": [{
        "name": "KRaft 单机起步模板（server.properties）",
        "desc": "Kafka 3.x KRaft 模式单节点；正式集群需先初始化存储并调整副本相关参数。",
        "content": """process.roles=broker,controller
node.id=1
controller.quorum.voters=1@192.0.2.30:9093
listeners=PLAINTEXT://0.0.0.0:9092,CONTROLLER://0.0.0.0:9093
advertised.listeners=PLAINTEXT://192.0.2.30:9092
controller.listener.names=CONTROLLER
listener.security.protocol.map=CONTROLLER:PLAINTEXT,PLAINTEXT:PLAINTEXT
inter.broker.listener.name=PLAINTEXT

log.dirs=/var/lib/kafka/data
num.partitions=6
num.network.threads=8
num.io.threads=16
socket.send.buffer.bytes=102400
socket.receive.buffer.bytes=102400
socket.request.max.bytes=104857600

# 单机部署把以下副本参数改为 1；三节点集群保持现值
default.replication.factor=3
offsets.topic.replication.factor=3
transaction.state.log.replication.factor=3
transaction.state.log.min.isr=2
min.insync.replicas=2

log.retention.hours=168
log.retention.bytes=107374182400
log.segment.bytes=1073741824
log.retention.check.interval.ms=300000
auto.create.topics.enable=false
delete.topic.enable=true
group.initial.rebalance.delay.ms=3000
"""}],
    "redis": [{
        "name": "生产单机模板（redis.conf）",
        "desc": "绑定内网 + 口令 + RDB/AOF 双持久化 + 内存上限与 LRU；口令为占位符。",
        "content": """bind 127.0.0.1 192.0.2.40
protected-mode yes
port 6379
tcp-backlog 1024
timeout 300
tcp-keepalive 300
daemonize no
supervised systemd
pidfile /run/redis/redis-server.pid
loglevel notice
logfile /var/log/redis/redis-server.log
databases 16

# RDB 快照
save 900 100
save 300 1000
save 60 10000
stop-writes-on-bgsave-error yes
rdbcompression yes
rdbchecksum yes
dbfilename dump.rdb
dir /var/lib/redis

# AOF
appendonly yes
appendfilename "appendonly.aof"
appendfsync everysec
no-appendfsync-on-rewrite no
auto-aof-rewrite-percentage 100
auto-aof-rewrite-min-size 4gb
aof-load-truncated yes

# 内存与淘汰
maxmemory 4gb
maxmemory-policy allkeys-lru
maxclients 10000
lazyfree-lazy-eviction yes

# 安全（占位口令必须替换；FLUSHALL 已禁用）
requirepass REPLACE_WITH_LOCAL_SECRET
rename-command FLUSHALL ""

slowlog-log-slower-than 10000
slowlog-max-len 256
latency-monitor-threshold 100
"""}],
    "docker": [{
        "name": "生产 daemon.json 模板",
        "desc": "日志轮转 + live-restore + 下载并发限制；镜像加速地址需替换为你自己的。",
        "content": """{
  "data-root": "/var/lib/docker",
  "registry-mirrors": ["https://REPLACE_WITH_YOUR_MIRROR"],
  "insecure-registries": [],
  "log-driver": "json-file",
  "log-opts": { "max-size": "20m", "max-file": "5" },
  "live-restore": true,
  "max-concurrent-downloads": 6,
  "max-concurrent-uploads": 4,
  "max-download-attempts": 5,
  "storage-driver": "overlay2",
  "default-address-pools": [{ "base": "172.30.0.0/16", "size": 24 }],
  "metrics-addr": "127.0.0.1:9323",
  "experimental": false
}
"""}],
}


def entries(spec: str, section: str, style: str, notes: str, danger_map: dict[str, str]) -> list[dict]:
    """紧凑维护配置资料，输出完整字段；默认值与建议示例分开。"""
    result = []
    for row in spec.strip().splitlines():
        name, default, value, desc, extra = row.split("|", 4)
        if style == "json":
            example = json.dumps({name: json.loads(value)}, ensure_ascii=False)
        elif style == "properties":
            example = f"{name}={value}"
        else:
            example = name + (" " + value if value else "")
        result.append({"name":name,"default":default,"section":section,"syntax":example,
                       "example":example,"desc":desc,"notes":notes + extra,
                       "danger":danger_map.get(name, "false"),"tags":[section]})
    return result


# conf 风险分级：false=参考信息；low=调优类，改错影响可控；medium=直接影响
# 高可用切换/数据保留/安全边界，误配可能导致业务中断或数据丢失。
DANGER: dict[str, dict[str, str]] = {
    "keepalived": {
        "medium": "script interval timeout weight fall rise state interface virtual_router_id "
                  "priority advert_int authentication virtual_ipaddress virtual_ipaddress_excluded "
                  "track_script track_interface nopreempt preempt_delay unicast_src_ip unicast_peer "
                  "vrrp_version vrrp_strict lb_algo lb_kind sorry_server real_server weight "
                  "delay_loop TCP_CHECK",
        "low": "router_id script_user enable_script_security notify_master notify_backup "
               "notify_fault notify_stop garp_master_delay vrrp_garp_master_repeat vrrp_sync_group "
               "persistence_timeout smtp_server vrrp_mcast_group4 vrrp_skip_check_adv_addr",
    },
    "kafka": {
        "medium": "broker.id listeners advertised.listeners listener.security.protocol.map "
                  "inter.broker.listener.name controller.listener.names log.dirs "
                  "default.replication.factor offsets.topic.replication.factor "
                  "transaction.state.log.replication.factor log.retention.hours log.retention.bytes "
                  "log.cleanup.policy delete.topic.enable auto.create.topics.enable "
                  "min.insync.replicas unclean.leader.election.enable zookeeper.connect "
                  "process.roles node.id controller.quorum.voters",
        "low": "num.network.threads num.io.threads socket.send.buffer.bytes "
               "socket.receive.buffer.bytes socket.request.max.bytes num.partitions "
               "num.recovery.threads.per.data.dir offsets.topic.num.partitions "
               "transaction.state.log.min.isr log.segment.bytes log.retention.check.interval.ms "
               "message.max.bytes replica.fetch.max.bytes group.initial.rebalance.delay.ms",
    },
    "redis": {
        "medium": "bind protected-mode port daemonize supervised save "
                  "stop-writes-on-bgsave-error dir appendonly appendfsync "
                  "no-appendfsync-on-rewrite maxmemory maxmemory-policy replicaof masterauth "
                  "requirepass rename-command min-replicas-to-write cluster-enabled "
                  "cluster-node-timeout",
        "low": "tcp-backlog timeout tcp-keepalive pidfile loglevel logfile databases "
               "rdbcompression rdbchecksum dbfilename appendfilename "
               "auto-aof-rewrite-percentage auto-aof-rewrite-min-size aof-load-truncated "
               "maxmemory-samples lazyfree-lazy-eviction replica-read-only repl-backlog-size "
               "repl-backlog-ttl min-replicas-max-lag maxclients io-threads "
               "slowlog-log-slower-than slowlog-max-len latency-monitor-threshold "
               "notify-keyspace-events cluster-config-file hz activedefrag lfu-log-factor "
               "lfu-decay-time",
    },
    "docker": {
        "medium": "data-root registry-mirrors insecure-registries log-driver log-opts "
                  "storage-driver live-restore hosts tls tlsverify tlscacert tlscert tlskey "
                  "seccomp-profile exec-opts cgroup-parent oom-score-adjust containerd "
                  "containerd-namespace default-address-pools fixed-cidr-v6 ipv6 "
                  "userland-proxy dns metrics-addr",
        "low": "max-concurrent-downloads max-concurrent-uploads default-shm-size "
               "max-download-attempts dns-search debug experimental default-ulimits features",
    },
}


def danger_lookup(software: str) -> dict[str, str]:
    """把分级字符串展开为 name → danger 映射；未列出的条目为 false。"""
    mapping: dict[str, str] = {}
    for level in ("medium", "low"):
        for name in DANGER[software][level].split():
            mapping[name] = level
    return mapping


def cli(spec: str) -> list[dict]:
    """命令只作为参考文本；高危项显式标记。"""
    result = []
    for row in spec.strip().splitlines():
        name, example, desc, danger, notes = row.split("|",4)
        result.append({"name":name,"syntax":name,"example":example,"desc":desc,"notes":notes,
                       "danger":False if danger == "false" else danger,"tags":["运行命令"]})
    return result


def main() -> None:
    """写入四份 UTF-8 YAML，保留 cli/conf 两类。"""
    software = {}
    software["keepalived"] = {
        "label":"Keepalived", "version_ref":"Keepalived 2.x；以本机 man keepalived.conf 为准",
        "sources":["https://www.keepalived.org/documentation/keepalived-conf/","https://keepalived.org/documentation/user-guide/configuration-synopsis/"],
        "cli":cli('''systemctl start keepalived|systemctl start keepalived|启动高可用服务。|medium|启动前确认 VRID、优先级与 VIP 不冲突。
systemctl stop keepalived|systemctl stop keepalived|停止服务，可能触发 VIP 漂移。|high|在维护窗口操作。
systemctl restart keepalived|systemctl restart keepalived|重启服务并重新选举。|high|先做语法检查，关注双主风险。
systemctl status keepalived|systemctl status keepalived|查看服务状态。|false|只读，无配置生效动作。
keepalived -t|keepalived -t -f /etc/keepalived/keepalived.conf|检查配置语法，不启动服务。|false|通过不代表网络与脚本运行一定正确。
keepalived -f|keepalived -f /etc/keepalived/keepalived.conf|使用指定配置启动。|medium|避免与 systemd 管理的实例重复启动。
keepalived --help|keepalived --help|查看本机支持的参数。|false|无配置生效动作。
keepalived -v|keepalived -v|查看版本与构建选项。|false|无配置生效动作。
ipvsadm -Ln|ipvsadm -Ln|查看 LVS 转发表。|false|需要单独安装 ipvsadm 和适当权限。
ipvsadm -C|ipvsadm -C|清空全部 IPVS 转发表。|high|会中断 LVS 转发，禁止未经确认在生产执行。
ip addr show|ip addr show dev eth0|查看接口地址与 VIP。|false|eth0 替换为实际接口。
journalctl -u keepalived|journalctl -u keepalived -f|跟踪服务日志。|false|Ctrl+C 停止查看。
tcpdump vrrp|tcpdump -ni eth0 proto 112|观察 VRRP 报文以排查双主。|low|通常需抓包权限；确认接口与报文方向。'''),
        "conf":entries('''router_id|主机名|LB_A|标识本节点，主要用于通知。|放在 global_defs 块。
script_user|keepalived_script 或 root|keepalived_script|设置检查脚本默认运行用户。|放在 global_defs，确保该用户存在。
enable_script_security|未启用||检查 root 脚本路径的安全权限。|放在 global_defs；建议开启。
script|必须指定|"/usr/local/bin/check_service.sh"|定义健康检查命令。|放在 vrrp_script chk_service 块；检查权限与返回码。
interval|1 秒|2|设置脚本检查周期。|vrrp_script 块，单位秒。
timeout|依版本与 interval|1|设置脚本执行超时。|vrrp_script 块，不应长于检查间隔。
weight|0| -10|设置脚本失败时的优先级权重。|vrrp_script 块；0 权重失败会进入 FAULT，非零权重调整优先级。
fall|1|2|连续失败达到阈值后判定失败。|vrrp_script 块。
rise|1|2|连续成功达到阈值后恢复。|vrrp_script 块。
state|BACKUP|BACKUP|设置 VRRP 初始状态。|vrrp_instance VI_1 块；最终角色由选举决定。
interface|必须指定|eth0|指定 VRRP 绑定接口。|vrrp_instance 块，先确认网卡名。
virtual_router_id|必须指定|51|指定同一 VRRP 组的标识。|vrrp_instance 块；同二层不同组不得冲突。
priority|100|100|设置选举优先级。|vrrp_instance 块；255 为地址所有者，普通节点使用 1–254。
advert_int|1 秒|1|设置通告间隔。|vrrp_instance 块，同组保持一致。
authentication|未配置|{ auth_type PASS; auth_pass example; }|描述 VRRPv2 简单认证。|仅语义示意，实际块内分行写且不使用分号；不是加密，VRRPv3 不支持此认证。
virtual_ipaddress|未设置|{ 192.0.2.10/24 dev eth0 }|配置接管的 VIP。|vrrp_instance 块；示例文档保留地址须替换，块内每行一条。
virtual_ipaddress_excluded|未设置|{ 192.0.2.11/24 dev eth0 }|管理不放入 VRRP 通告的额外地址。|仍随实例状态增删，注意路由。
track_script|未设置|{ chk_service }|绑定已定义的检查脚本。|vrrp_instance 块，与 vrrp_script 名一致。
track_interface|未设置|{ eth0 }|跟踪网卡状态。|vrrp_instance 块。
nopreempt|默认允许抢占||禁用高优先级节点恢复后的主动抢占。|初始 state 必须是 BACKUP；没有独立 preempt 指令，默认即抢占。
preempt_delay|0 秒|30|延迟恢复节点的抢占。|与 nopreempt 的效果区分，初始 BACKUP。
garp_master_delay|5 秒|5|设置成为主节点后第二批免费 ARP 的延迟。|vrrp_instance 块，单位秒。
notify_master|未设置|"/usr/local/bin/notify.sh master"|成为 MASTER 后调用通知脚本。|脚本需审阅并限制权限。
notify_backup|未设置|"/usr/local/bin/notify.sh backup"|成为 BACKUP 后调用脚本。|vrrp_instance 块。
notify_fault|未设置|"/usr/local/bin/notify.sh fault"|进入 FAULT 时调用脚本。|vrrp_instance 块。
notify_stop|未设置|"/usr/local/bin/notify.sh stop"|停止实例时调用脚本。|vrrp_instance 块。
unicast_src_ip|未设置|192.0.2.1|指定单播 VRRP 源地址。|vrrp_instance 块。
unicast_peer|未设置|{ 192.0.2.2 }|配置单播对端列表。|vrrp_instance 块；确认双方网络和防火墙。
vrrp_garp_master_repeat|5|5|设置成为主节点发送免费 ARP 的次数。|global_defs 块。
vrrp_sync_group|未设置|VG_1 { group { VI_1 } }|同步多个实例的状态。|顶层块，真实配置建议多行书写。
delay_loop|60 秒|5|设置 LVS 检查轮询周期。|virtual_server 块。
lb_algo|wlc|rr|设置 IPVS 调度算法。|virtual_server 块，可选 rr/wlc/lc/sh/dh 等。
lb_kind|NAT|DR|指定 NAT、DR 或 TUN 转发。|virtual_server 块，配套后端网络配置。
persistence_timeout|未启用持久性|50|设置会话持久性秒数。|virtual_server 块。
protocol|UDP|TCP|设置虚拟服务协议。|virtual_server 块，应显式配置。
sorry_server|未设置|192.0.2.30 80|设置全部后端失效时的备用服务器。|virtual_server 块。
real_server weight|1|1|设置真实服务器转发权重。|写法为 real_server 192.0.2.20 80 { weight 1 }。
TCP_CHECK|未设置|{ connect_timeout 3 }|使用 TCP 连接健康检查。|real_server 块，另有 HTTP_GET/SSL_GET/MISC_CHECK，参数不同。
notify_up|未设置|"/usr/local/bin/backend_up.sh"|后端恢复时通知。|real_server 块。
notify_down|未设置|"/usr/local/bin/backend_down.sh"|后端故障时通知。|real_server 块。
smtp_server|未设置|192.0.2.25|指定告警邮件服务器。|global_defs 块，配合 notification_email。
vrrp_mcast_group4|224.0.0.18|224.0.0.18|设置 IPv4 VRRP 多播组。|global_defs 块，同组节点一致。
vrrp_skip_check_adv_addr|未启用||在已知主节点的连续通告中跳过地址校验。|global_defs 块，需评估校验与性能。
vrrp_strict|未启用||启用严格 VRRP 兼容检查。|global_defs 块，可能限制单播及认证等扩展。
vrrp_version|2|3|指定默认 VRRP 版本。|global_defs 块，同组版本必须一致。''',"vrrp","space","改动先 keepalived -t，再按服务支持 reload 或维护窗口重启；", danger_lookup("keepalived"))}
    software["kafka"] = {
        "label":"Kafka", "version_ref":"Apache Kafka 3.x（3.8 参考），标明 ZK/KRaft 区别",
        "sources":["https://kafka.apache.org/38/configuration/broker-configs/","https://kafka.apache.org/38/operations/basic-kafka-operations/"],
        "cli":cli('''kafka-server-start.sh|bin/kafka-server-start.sh -daemon config/server.properties|启动 broker。|medium|确认 KRaft 存储已按部署流程初始化，或 ZK 集群可用。
systemctl status kafka|systemctl status kafka|查看发行版 Kafka 服务。|false|systemd 单元需自行部署。
systemctl stop kafka|systemctl stop kafka|停止 broker。|high|逐台维护并确认 ISR。
systemctl restart kafka|systemctl restart kafka|重启 broker。|high|使用滚动重启，避免同时停多数副本。
kafka-topics.sh --create|bin/kafka-topics.sh --bootstrap-server localhost:9092 --create --topic demo --partitions 3 --replication-factor 1|创建主题。|medium|副本数 1 仅用于单机演示，生产评估副本与 ISR。
kafka-topics.sh --list|bin/kafka-topics.sh --bootstrap-server localhost:9092 --list|列出主题。|false|只读。
kafka-topics.sh --describe|bin/kafka-topics.sh --bootstrap-server localhost:9092 --describe --topic demo|查看分区与副本。|false|关注 leader 和 ISR。
kafka-topics.sh --alter|bin/kafka-topics.sh --bootstrap-server localhost:9092 --alter --topic demo --partitions 6|增加主题分区。|high|不能通过此命令减少分区，可能改变键分区映射。
kafka-topics.sh --delete|bin/kafka-topics.sh --bootstrap-server localhost:9092 --delete --topic demo|删除主题及数据。|high|不可恢复，先确认主题和备份。
kafka-console-producer.sh|bin/kafka-console-producer.sh --bootstrap-server localhost:9092 --topic demo|交互发送消息。|medium|输入内容会写入目标主题。
kafka-console-consumer.sh|bin/kafka-console-consumer.sh --bootstrap-server localhost:9092 --topic demo --from-beginning --group demo-reader|从头读取消息。|low|使用独立测试组，避免影响生产消费进度。
kafka-consumer-groups.sh --list|bin/kafka-consumer-groups.sh --bootstrap-server localhost:9092 --list|列出消费者组。|false|只读。
kafka-consumer-groups.sh --describe|bin/kafka-consumer-groups.sh --bootstrap-server localhost:9092 --describe --group demo-reader|查看消费位点和积压。|false|只读。
kafka-consumer-groups.sh --reset-offsets|bin/kafka-consumer-groups.sh --bootstrap-server localhost:9092 --reset-offsets --group demo-reader --topic demo --to-earliest --dry-run|预览重置消费位点。|high|先停止组消费者；dry-run 不写入，确认后才考虑 --execute，可能重复消费。
kafka-configs.sh --describe|bin/kafka-configs.sh --bootstrap-server localhost:9092 --entity-type topics --entity-name demo --describe|查看动态配置。|false|只读。
kafka-configs.sh --alter|bin/kafka-configs.sh --bootstrap-server localhost:9092 --entity-type topics --entity-name demo --alter --add-config retention.ms=86400000|修改主题保留时间。|high|缩短保留期会清理数据；仅动态配置直接生效。
kafka-log-dirs.sh --describe|bin/kafka-log-dirs.sh --bootstrap-server localhost:9092 --describe|查看副本目录占用。|false|只读。
kafka-cluster.sh cluster-id|bin/kafka-cluster.sh cluster-id --bootstrap-server localhost:9092|查询集群 ID。|false|以本机脚本 --help 为准。
kafka-broker-api-versions.sh|bin/kafka-broker-api-versions.sh --bootstrap-server localhost:9092|查看 broker 支持的协议版本。|false|只读。
kafka-acls.sh|bin/kafka-acls.sh --bootstrap-server localhost:9092 --list|列出访问控制规则。|false|添加或删除 ACL 需先评估生产权限。'''),
        "conf":entries('''broker.id|-1|1|ZK 模式 broker 唯一标识。|KRaft 使用 node.id。
listeners|PLAINTEXT://:9092|PLAINTEXT://127.0.0.1:9092|设置监听端点。|不要将不认证的端口暴露公网。
advertised.listeners|取 listeners|PLAINTEXT://localhost:9092|设置客户端可访问的通告地址。|多机环境不能填写 localhost。
listener.security.protocol.map|内置名称映射|PLAINTEXT:PLAINTEXT,CONTROLLER:PLAINTEXT|映射监听名称与协议。|生产评估 SSL/SASL。
inter.broker.listener.name|未设置|PLAINTEXT|指定 broker 间监听名称。|与 security.inter.broker.protocol 不要冲突。
controller.listener.names|未设置|CONTROLLER|指定 KRaft controller 监听名称。|仅 KRaft；必须与 listeners/map 配套。
num.network.threads|3|3|网络请求处理线程数。|按连接负载调优。
num.io.threads|8|8|请求及磁盘处理线程数。|按 CPU/磁盘评估。
socket.send.buffer.bytes|102400|102400|发送缓冲区字节数。|与操作系统限制配合。
socket.receive.buffer.bytes|102400|102400|接收缓冲区字节数。|与操作系统限制配合。
socket.request.max.bytes|104857600|104857600|限制单次请求大小。|防止过大请求占用内存。
log.dirs|取 log.dir|/var/lib/kafka/data|设置数据日志目录。|不要放临时目录，变更须迁移数据。
num.partitions|1|3|自动建主题的默认分区数。|不改变已存在主题。
num.recovery.threads.per.data.dir|1|1|每目录恢复与刷盘线程数。|按存储吞吐评估。
default.replication.factor|1|3|自动创建主题默认副本数。|不能超过可用 broker 数。
offsets.topic.num.partitions|50|50|消费位点主题分区数。|部署前规划，后续不宜调整。
offsets.topic.replication.factor|3|3|消费位点主题副本数。|单机演示需显式降为 1，生产保留冗余。
transaction.state.log.replication.factor|3|3|事务状态主题副本数。|事务初始化需要足够 broker。
transaction.state.log.min.isr|2|2|事务状态主题最少同步副本数。|与副本数协调。
log.retention.hours|168|168|默认日志保留小时数。|主题覆盖配置优先，缩短可能删除历史数据。
log.retention.bytes|-1|1073741824|每分区保留字节数限制。|-1 表示不按大小限制。
log.segment.bytes|1073741824|1073741824|数据段大小。|影响滚动与清理粒度。
log.retention.check.interval.ms|300000|300000|保留期检查周期。|单位毫秒。
log.cleanup.policy|delete|delete|配置删除或压缩策略。|日志压缩通过 compact 或主题 cleanup.policy，不存在 log.compaction 这个通用配置键。
delete.topic.enable|true|true|允许删除主题。|生产删除应受权限控制。
auto.create.topics.enable|true|false|控制自动创建主题。|关闭可避免拼错名称意外建主题。
message.max.bytes|1048588|1048588|broker 可接受的最大记录批次。|同时检查生产者、主题及副本拉取限制。
replica.fetch.max.bytes|1048576|1048576|副本每分区拉取目标上限。|首个超大批次可能仍返回以保证进度。
min.insync.replicas|1|2|acks=all 下写入要求的最小 ISR。|与副本数及容错目标一致。
unclean.leader.election.enable|false|false|控制是否允许非同步副本当选。|启用可能丢数据。
group.initial.rebalance.delay.ms|3000|3000|新组首次重平衡延迟。|单位毫秒。
zookeeper.connect|未设置|localhost:2181|ZK 模式连接串。|Kafka 3.x 的 ZK 模式；KRaft 不填写。
process.roles|空（ZK 模式）|broker,controller|KRaft 节点角色。|组合模式仅建议小规模或演示部署。
node.id|必须为 KRaft 配置|1|KRaft 节点唯一 ID。|与 quorum voters 的 ID 一致。
controller.quorum.voters|空|1@localhost:9093|静态 KRaft quorum 成员。|3.x 静态投票配置，多机地址需可达。
advertised.host.name|旧版已废弃|localhost|历史版本的通告主机名。|Kafka 3.x 不再使用，改用 advertised.listeners；此行仅迁移说明，不应写入新配置。''',"broker","properties","server.properties 修改通常需滚动重启；支持动态更新的键可经 kafka-configs 管理；", danger_lookup("kafka"))}
    software["redis"] = {
        "label":"Redis", "version_ref":"Redis OSS 7.x（7.2 示例配置参考）",
        "sources":["https://github.com/redis/redis/blob/7.2/redis.conf","https://redis.io/docs/latest/commands/"],
        "cli":cli('''systemctl start redis|systemctl start redis|启动 Redis 服务。|medium|发行版服务名可能是 redis-server。
systemctl stop redis|systemctl stop redis|停止 Redis 服务。|high|先确认持久化与主从切换。
systemctl restart redis|systemctl restart redis|重启服务。|high|在维护窗口执行。
systemctl status redis|systemctl status redis|查看服务状态。|false|只读。
redis-cli ping|redis-cli ping|测试响应。|false|正常返回 PONG。
redis-cli -h -p -a|redis-cli -h 127.0.0.1 -p 6379 --askpass|指定连接并交互输入口令。|low|-a 会将口令暴露在进程参数，推荐 --askpass 或受控环境变量。
redis-cli info|redis-cli info memory|查看运行指标。|false|只读。
redis-cli config get|redis-cli config get maxmemory|查看配置。|false|访问需 ACL 授权。
redis-cli config set|redis-cli config set maxmemory 256mb|动态设置内存上限。|high|可能触发淘汰；CONFIG REWRITE 或文件持久化另行确认。
redis-cli bgsave|redis-cli bgsave|后台生成 RDB。|medium|评估 fork 内存和磁盘空间。
redis-cli save|redis-cli save|同步生成 RDB，期间阻塞请求。|high|生产优先评估 BGSAVE。
redis-cli lastsave|redis-cli lastsave|查看最近 RDB 成功保存时间戳。|false|只读。
redis-cli dbsize|redis-cli dbsize|查看当前库键数量。|false|只读。
redis-cli --scan|redis-cli --scan --pattern 'session:*'|增量遍历匹配键。|low|避免生产 KEYS *；SCAN 可能重复且不是一致快照。
redis-cli slowlog get|redis-cli slowlog get 10|查看慢命令。|false|可能包含业务参数，注意本机展示范围。
redis-cli client list|redis-cli client list|查看客户端。|false|只读。
redis-cli client kill|redis-cli client kill ID 12345|断开指定客户端。|high|先从 CLIENT LIST 确认 ID。
redis-benchmark|redis-benchmark -h 127.0.0.1 -p 6379 -n 1000 -c 5 -t ping|执行小规模 PING 基准。|medium|仅测试环境，压测仍消耗资源。
redis-check-rdb|redis-check-rdb /var/lib/redis/dump.rdb|检查 RDB 文件。|false|对副本文件检查，避免与写入并发。
redis-cli --latency|redis-cli --latency|采样连接延迟。|low|Ctrl+C 停止。'''),
        "conf":entries('''bind|未指定时所有接口；示例文件为回环|127.0.0.1 -::1|限制监听地址。|生产不要无认证暴露公网。
protected-mode|yes|yes|启用保护模式。|不替代防火墙与 ACL。
port|6379|6379|指定 TCP 端口。|0 禁用普通 TCP。
tcp-backlog|511|511|设置监听队列长度。|受系统 somaxconn 限制。
timeout|0|0|空闲客户端超时秒数。|0 不主动因空闲关闭。
tcp-keepalive|300|300|设置 TCP keepalive 秒数。|与网络设备超时协调。
daemonize|no|no|是否后台化。|systemd 通常使用 no。
supervised|no|systemd|设置进程监督方式。|以发行版单元配置为准。
pidfile|/var/run/redis.pid|/run/redis/redis-server.pid|指定 PID 文件。|目录需可写。
loglevel|notice|notice|设置日志级别。|debug 会增加日志量。
logfile|空（标准输出）|""|指定日志文件。|空字符串配合 systemd journal。
databases|16|16|设置逻辑数据库数量。|集群模式只支持 DB 0。
save|3600 1 300 100 60 10000|900 1|设置 RDB 快照触发规则。|可多行；save "" 禁用自动快照，须评估恢复目标。
stop-writes-on-bgsave-error|yes|yes|RDB 后台保存失败时停止写入。|排查磁盘与权限，不应仅关闭保护。
rdbcompression|yes|yes|启用 RDB 压缩。|影响 CPU 与文件大小。
rdbchecksum|yes|yes|启用 RDB 校验和。|有少量计算开销。
dbfilename|dump.rdb|dump.rdb|指定 RDB 文件名。|配合 dir。
dir|./|/var/lib/redis|持久化文件目录。|目录权限与容量需确认。
appendonly|no|yes|启用 AOF。|切换前评估当前持久化及磁盘。
appendfilename|appendonly.aof|"appendonly.aof"|指定 AOF 基础名称。|7.x 多部分 AOF 使用 appenddirname 子目录。
appendfsync|everysec|everysec|设置 AOF 同步策略。|always/everysec/no 的性能和丢失窗口不同。
no-appendfsync-on-rewrite|no|no|重写期间是否跳过 fsync。|yes 可能扩大数据丢失窗口。
auto-aof-rewrite-percentage|100|100|AOF 自动重写增长百分比。|0 禁用自动重写。
auto-aof-rewrite-min-size|64mb|64mb|自动重写最低大小。|与百分比条件共同生效。
aof-load-truncated|yes|yes|是否接受尾部截断的 AOF。|排查前保留损坏文件副本。
maxmemory|0|256mb|设置最大内存。|0 通常表示不设限；预留 fork 和系统内存。
maxmemory-policy|noeviction|allkeys-lru|设置达到上限后的处理策略。|会淘汰数据，按缓存或存储语义选择。
maxmemory-samples|5|5|设置近似淘汰采样数。|样本增多提高 CPU 开销。
lazyfree-lazy-eviction|no|yes|异步释放淘汰键内存。|减少主线程释放开销。
replicaof|未设置|192.0.2.10 6379|配置复制上游。|旧名 slaveof；切换角色需备份并确认数据覆盖。
masterauth|未设置|"REPLACE_WITH_LOCAL_SECRET"|设置上游认证口令。|占位符必须在本机替换，不在知识库填写真实口令。
replica-read-only|yes|yes|限制副本写入。|不提供网络访问控制。
repl-backlog-size|1mb|1mb|复制积压缓冲区大小。|按断连时间与写入速率估算。
repl-backlog-ttl|3600|3600|无副本时保留积压缓冲的秒数。|0 表示一直保留。
min-replicas-to-write|0|1|限制写入所需健康副本数。|可能降低可用性，配合 max-lag。
min-replicas-max-lag|10|10|健康副本最大延迟秒数。|与 min-replicas-to-write 配合。
requirepass|未设置|"REPLACE_WITH_LOCAL_SECRET"|设置默认用户口令。|7.x 推荐 ACL；不得以知识库示例口令上线。
rename-command|未设置|CONFIG ""|历史方式禁用命令。|已不推荐，优先 ACL；禁用 CONFIG 影响运维。
maxclients|10000|10000|设置最大客户端数。|受文件描述符限制。
io-threads|1|4|设置 I/O 线程数。|按核数与负载测试，不能假定命令执行并行。
slowlog-log-slower-than|10000|10000|慢日志阈值微秒。|0 记录所有，负值禁用。
slowlog-max-len|128|128|慢日志最大条数。|按排障窗口规划。
latency-monitor-threshold|0|100|延迟事件阈值毫秒。|0 禁用延迟监控。
notify-keyspace-events|空|"Ex"|启用键空间事件通知。|Ex 表示键事件过期通知，注意额外开销。
cluster-enabled|no|no|控制 Redis Cluster 模式。|更改需要完整集群规划。
cluster-config-file|nodes.conf|nodes.conf|集群自动维护的状态文件。|不要手工改写该文件。
cluster-node-timeout|15000|15000|集群节点超时毫秒。|需与网络和故障切换目标协调。
hz|10|10|后台周期任务基准频率。|过高会增加 CPU。
activedefrag|no|no|启用主动碎片整理。|要求支持的分配器构建，按内存与 CPU 评估。
lfu-log-factor|10|10|LFU 计数对数增长因子。|仅 LFU 淘汰策略相关。
lfu-decay-time|1|1|LFU 计数衰减分钟数。|配合 LFU 策略评估。''',"server","space","改文件后维护窗口重启；支持的参数可 CONFIG SET 热改，持久化需另行确认；", danger_lookup("redis"))}
    software["docker"] = {
        "label":"Docker", "version_ref":"Docker Engine 24+/26+；部分功能依平台与版本",
        "sources":["https://docs.docker.com/reference/cli/dockerd/","https://docs.docker.com/reference/cli/docker/"],
        "cli":cli('''docker run|docker run -d --name web -p 127.0.0.1:8080:80 --restart unless-stopped nginx:1.26|创建并启动容器。|medium|镜像需事先导入；需要下载时使用用户配置的华为镜像，检查端口/挂载/网络。
docker ps|docker ps -a|列出容器。|false|只读。
docker images|docker images|列出本地镜像。|false|只读。
docker pull|docker pull swr.cn-north-4.myhuaweicloud.com/REPLACE_NAMESPACE/REPLACE_IMAGE:REPLACE_TAG|从华为 SWR 拉取镜像。|low|占位地址必须换成有权限的真实仓库，私有仓库先登录。
docker push|docker push swr.cn-north-4.myhuaweicloud.com/REPLACE_NAMESPACE/REPLACE_IMAGE:REPLACE_TAG|推送镜像到华为 SWR。|medium|会上传镜像内容，先确认目标和敏感信息。
docker start|docker start web|启动已有容器。|medium|确认端口与挂载。
docker stop|docker stop --time 30 web|优雅停止容器。|high|影响业务，超时后会强制终止。
docker restart|docker restart --time 30 web|重启容器。|high|在维护窗口操作。
docker rm|docker rm web|删除已停止的容器。|high|-f 强制停止后删除；可写层数据会丢失。
docker rmi|docker rmi example/app:test|删除本地镜像。|high|确认没有需要保留的标签或依赖。
docker logs|docker logs --tail 100 -f web|跟踪容器日志。|false|只读，避免暴露业务敏感内容。
docker exec|docker exec -it web sh|进入容器执行 shell。|medium|shell 中的后续命令会修改容器，需人工审阅。
docker inspect|docker inspect web|查看容器元数据。|false|输出可能包含环境变量口令。
docker stats|docker stats --no-stream|查看资源使用。|false|只读。
docker cp|docker cp web:/etc/nginx/nginx.conf ./nginx.conf|复制容器文件到本机。|low|确认目标文件不会被覆盖。
docker top|docker top web|查看容器进程。|false|只读。
docker build|docker build --pull=false -t example/app:test .|从 Dockerfile 构建镜像。|medium|基础镜像先从华为镜像拉取并按需改 FROM，审阅构建上下文及脚本。
docker tag|docker tag example/app:test example/app:reviewed|添加本地镜像标签。|low|不会上传镜像。
docker network|docker network ls|列出网络。|false|create/inspect 子命令分别用于创建/查看，先规划网段。
docker volume|docker volume ls|列出数据卷。|false|inspect 查看详情；不要未经确认删除卷。
docker compose|docker compose ps|查看 Compose 服务。|false|up -d 会启动，down 会停服务，down -v 会删除卷；logs 用于查看。
docker system df|docker system df|查看 Docker 空间占用。|false|只读。
docker system prune|docker system prune|清理未使用对象。|high|先确认交互提示；--volumes/-a 扩大删除范围，不可恢复。
docker info|docker info|查看引擎状态。|false|只读。
docker version|docker version|查看客户端和引擎版本。|false|只读。
docker login|docker login swr.cn-north-4.myhuaweicloud.com|登录华为镜像仓库。|medium|交互输入，不把口令写入命令行或项目。'''),
        "conf":entries('''data-root|/var/lib/docker|"/var/lib/docker"|设置引擎持久数据目录。|更换路径需要停服务并迁移数据。
registry-mirrors|[]|[]|设置兼容镜像加速器。|华为个人加速地址由控制台获取后填入数组，不编造可用地址。
insecure-registries|[]|[]|允许指定的不安全仓库。|优先配置可信 TLS，避免扩大明文访问。
log-driver|json-file|"local"|设置新容器默认日志驱动。|已有容器需重建才能应用默认值。
log-opts|{}|{"max-size":"10m","max-file":"3"}|设置日志轮转选项。|max-size/max-file 取字符串，仅用于支持它们的日志驱动。
storage-driver|平台自动选择|"overlay2"|设置存储驱动。|Linux 前提是受支持的文件系统；切换可能使旧镜像不可见。
live-restore|false|true|守护进程短暂不可用时保留容器。|不适用于所有升级与集群场景。
max-concurrent-downloads|3|3|设置每次拉取并行下载层数。|按网络带宽评估。
max-concurrent-uploads|5|5|设置并行上传层数。|按网络带宽评估。
default-shm-size|64MiB|"64M"|设置容器默认共享内存大小。|通常只对新容器生效。
max-download-attempts|5|5|设置镜像层下载重试数。|排查镜像源与代理，勿仅增加重试。
dns|主机解析配置|["192.0.2.53"]|设置容器默认 DNS。|示例保留地址需替换为可达 DNS。
dns-search|主机配置|["example.test"]|设置 DNS 搜索域。|使用自有域。
hosts|unix:///var/run/docker.sock|["unix:///var/run/docker.sock"]|指定守护进程监听。|与 systemd -H 参数冲突会启动失败；不要裸露远程 API。
tls|false|false|控制 TLS 传输。|生产远程访问应设置 tlsverify 与证书，tls 本身不等于客户端认证。
tlsverify|false|true|校验远程客户端证书。|必须配套 CA、服务端证书和私钥。
tlscacert|用户目录 .docker/ca.pem|"/etc/docker/tls/ca.pem"|设置信任 CA 路径。|与 TLS 配套。
tlscert|用户目录 .docker/cert.pem|"/etc/docker/tls/server-cert.pem"|设置服务端证书。|证书 SAN 应包含连接地址。
tlskey|用户目录 .docker/key.pem|"/etc/docker/tls/server-key.pem"|设置私钥文件。|限制读取权限，不上传私钥。
debug|false|false|控制调试日志。|开启会增加日志量与敏感信息暴露面。
experimental|false|false|启用实验特性。|依版本确认，不用于未经验证的生产变更。
metrics-addr|未启用|"127.0.0.1:9323"|开放 Prometheus 指标。|绑定回环或受控网络。
default-address-pools|引擎自动选择|[{"base":"172.30.0.0/16","size":24}]|为新网络规划默认地址池。|避免与现有路由、VPN 冲突。
default-ulimits|{}|{"nofile":{"Name":"nofile","Hard":65536,"Soft":65536}}|配置容器默认资源限制。|根据服务实际需求评估。
ipv6|false|false|控制默认 bridge 的 IPv6。|需配合 IPv6 网段和路由。
fixed-cidr-v6|未设置|"2001:db8:1::/64"|设置默认 bridge 的 IPv6 子网。|文档保留网段，替换后使用。
userland-proxy|true|true|控制用户态端口代理。|行为与防火墙和网络模式有关。
seccomp-profile|内置默认策略|"/etc/docker/seccomp.json"|指定默认 seccomp 策略。|需存在的有效策略文件，不应使用 unconfined 绕过隔离。
exec-opts|依平台|["native.cgroupdriver=systemd"]|设置引擎执行选项。|与宿主机 cgroup 管理方式一致。
features|依版本|{"buildkit":true}|设置特性开关。|24/26 可用性以本机版本为准，Buildx/BuildKit 行为也取决于客户端。
containerd|自动管理|"/run/containerd/containerd.sock"|指定外部 containerd socket。|命名空间另用 containerd-namespace，不能把命名空间当此字段值。
containerd-namespace|moby|"moby"|指定容器使用的 containerd 命名空间。|与现有运行时部署保持一致。
cgroup-parent|依平台|"docker.slice"|设置容器默认父 cgroup。|示例适用于 systemd driver。
oom-score-adjust|-500|-500|调整守护进程 OOM 优先级。|错误配置可能导致引擎或宿主关键进程被杀。''',"daemon","json","daemon.json 先 dockerd --validate --config-file /etc/docker/daemon.json；部分项支持 reload，其余维护窗口重启；", danger_lookup("docker"))}
    directory = Path(__file__).resolve().parents[1]/"data"/"kb"
    for name, data in software.items():
        payload = {"software":name, "label":data["label"], "version_ref":data["version_ref"],
                   "generated":"AI 整理，使用前请核对官方文档", "sources":data["sources"],
                   "templates":TEMPLATES[name],
                   "categories":[{"id":"cli","label":"启停与运行命令","entries":data["cli"]},
                                 {"id":"conf","label":"配置参数","entries":data["conf"]}]}
        if name == "keepalived":
            for item in payload["categories"][1]["entries"]:
                if item["name"] in {"router_id","script_user","enable_script_security","vrrp_garp_master_repeat","smtp_server","vrrp_mcast_group4","vrrp_skip_check_adv_addr","vrrp_strict","vrrp_version"}:
                    item["section"] = "global"
                elif item["name"] in {"delay_loop","lb_algo","lb_kind","persistence_timeout","protocol","sorry_server","real_server weight","TCP_CHECK","notify_up","notify_down"}:
                    item["section"] = "virtual_server"
                if item["name"] == "authentication":
                    item["example"] = 'authentication {\n  auth_type PASS\n  auth_pass example\n}'
                    item["syntax"] = item["example"]
                if item["name"] == "real_server weight":
                    item["example"] = "real_server 192.0.2.20 80 {\n  weight 1\n}"
                    item["syntax"] = item["example"]
        (directory/(name+".yaml")).write_text(yaml.safe_dump(payload,allow_unicode=True,sort_keys=False),encoding="utf-8")
        print(name, len(data["cli"]), len(data["conf"]))


if __name__ == "__main__":
    main()
