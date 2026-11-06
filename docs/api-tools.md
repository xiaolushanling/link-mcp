# 接口工具目录

从官网 OpenAPI 快照生成。实际字段以 `link_describe_api` 返回的定义为准。

| 服务 | MCP 工具 | 用途 | 只读 | HTTP 路径 |
| --- | --- | --- | --- | --- |
| 用户服务 | `link_user_oauth_login` | oauth登录 | 否 | `POST /userservice/openapi/oauthLogin` |
| 用户服务 | `link_user_get_receive_warehouse` | 获取收货仓库 | 是 | `POST /userservice/openapi/getReceiveWarehouse` |
| 用户服务 | `link_user_get_owms_warehouse` | 获取海外仓仓库 | 是 | `POST /userservice/openapi/getOwmsWarehouse` |
| 国际物流 | `link_lms_upload_no` | 上传单号 | 否 | `POST /lmsservice/openapi/uploadNo` |
| 国际物流 | `link_lms_upload_file` | 上传文件 | 否 | `POST /lmsservice/openapi/uploadFile` |
| 国际物流 | `link_lms_special_line_order` | 专线下单 | 否 | `POST /lmsservice/openapi/specialLineOrder` |
| 国际物流 | `link_lms_query_tracks` | 查询轨迹 | 是 | `POST /lmsservice/openapi/queryTracks` |
| 国际物流 | `link_lms_push_post` | 推送数据 | 否 | `POST /lmsservice/openapi/push` |
| 国际物流 | `link_lms_print` | 打印文件 | 否 | `POST /lmsservice/openapi/print` |
| 国际物流 | `link_lms_order_detail` | 运单详情 | 是 | `POST /lmsservice/openapi/orderDetail` |
| 国际物流 | `link_lms_express_order` | 快递下单 | 否 | `POST /lmsservice/openapi/expressOrder` |
| 国际物流 | `link_lms_dws_upload_file` | dws文件上传 | 否 | `POST /lmsservice/openapi/dwsUploadFile` |
| 国际物流 | `link_lms_dws_upload_data_post` | dws上传数据 | 否 | `POST /lmsservice/openapi/dwsUploadData` |
| 国际物流 | `link_lms_delete_order` | 删除订单 | 否 | `POST /lmsservice/openapi/deleteOrder` |
| 尾派制单 | `link_pds_print` | 打印文件 | 否 | `POST /pdsservice/openapi/print` |
| 尾派制单 | `link_pds_order` | 下单 | 否 | `POST /pdsservice/openapi/order` |
| 尾派制单 | `link_pds_order_detail` | 运单详情 | 是 | `POST /pdsservice/openapi/orderDetail` |
| 尾派制单 | `link_pds_order_by_cal_price` | 根据试算id下单 | 否 | `POST /pdsservice/openapi/orderByCalPrice` |
| 尾派制单 | `link_pds_cancel` | 取消运单 | 否 | `POST /pdsservice/openapi/cancel` |
| 尾派制单 | `link_pds_cal_price` | 运费试算 | 否 | `POST /pdsservice/openapi/calPrice` |
| 结算服务 | `link_finance_query_price` | 查价 | 是 | `POST /financeservice/openapi/queryPrice` |
| 结算服务 | `link_finance_fetch_available_products` | 获取可用服务产品 | 是 | `POST /financeservice/openapi/fetchAvailableProducts` |
| 结算服务 | `link_finance_balance` | 查询余额 | 是 | `POST /financeservice/openapi/balance` |
| 综合服务 | `link_edge_push_post` | 推送数据 | 否 | `POST /edgeservice/openapi/push` |
| 基础数据 | `link_basicdata_validate_remote` | 偏远验证 | 是 | `POST /basicdataservice/openapi/validateRemote` |
| 基础数据 | `link_basicdata_validate_address` | 地址验证 | 是 | `POST /basicdataservice/openapi/validateAddress` |
| 基础数据 | `link_basicdata_city_post_code_search` | 城市邮编查询 | 是 | `POST /basicdataservice/openapi/cityPostCodeSearch` |

另有 `link_list_services`、`link_search_apis`、`link_describe_api` 三个本地文档工具。

只读按业务语义列举。打印、运费试算及第三方登录可能触发服务端流程，按非只读保守标注。
