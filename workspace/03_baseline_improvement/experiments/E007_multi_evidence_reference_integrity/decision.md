# E007 Decision

状态：`PREREGISTERED / DEVELOPMENT_NOT_RUN / DO_NOT_SUBMIT`

- control/treatment 尚未调用 API；
- prospective selection 尚未创建；
- candidate、answer.csv、上传、push 和 main merge 均未授权；
- 下一合法动作：冻结 runner、Prompt、Parser、输入与输出槽的 SHA256，通过全量测试后运行
  development control，再运行一次 treatment。
