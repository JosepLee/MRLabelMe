import json

with open('D:\\PycharmProjects\\labelmeFile\\Version\\CopyAll\\labelme-main\\labelme\\demo_data\\Untitled-1.json','r',encoding='utf8')as fp:
    json_data = json.load(fp)
    print('这是文件中的json数据：',json_data)
    print('这是读取到文件数据的数据类型：', type(json_data))