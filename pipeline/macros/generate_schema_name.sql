{# 自定义 schema 命名：直接使用 model 声明的 schema（staging/intermediate/marts），
   不拼接 target.schema，保持库名干净 #}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}
        {{ target.schema }}
    {%- else -%}
        {{ custom_schema_name | trim }}
    {%- endif -%}
{%- endmacro %}
