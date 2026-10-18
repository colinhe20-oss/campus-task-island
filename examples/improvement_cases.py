"""Explicit reference annotations. Model inputs never contain these labels."""
from datetime import datetime,timedelta,timezone

AT=datetime(2030,1,1,tzinfo=timezone.utc)


def draft():
    return dict(title='校园环保公益行动',description='开展校园垃圾清理并拍摄公益宣传素材',organization_name='演示公益社团',information_source='演示公告',contact='站内联系',
      recognition_conditions='按实际服务由负责人核验',starts_at='2030-01-05T14:00:00+08:00',ends_at='2030-01-05T16:00:00+08:00',
      opens_at='2030-01-01T08:00:00+08:00',closes_at='2030-01-04T18:00:00+08:00',registration_mode='direct',
      jobs=[dict(name=name,description=description,requirements=requirements,location='紫金港活动中心',starts_at='2030-01-05T14:00:00+08:00',ends_at='2030-01-05T16:00:00+08:00',capacity=n,estimated_minutes=120,estimated_hours_description='按实际服务确认')
            for name,description,requirements,n in [('清洁岗','清理校园垃圾','能按时到场',12),('摄影岗','记录公益活动','需要会摄影，器材待确认',8)]])


PLANNING_CASES=[
 dict(id='clarify',message='周末想组织一次志愿活动，但内容、时间、地点都没定。请先帮我明确最关键的问题，不要替我决定。',seed=False,expect='clarify'),
 dict(id='roles',message='请评估这次环保志愿活动，给出有依据的岗位分工建议，建议先不写进正式字段。',review=True,expect='review'),
 dict(id='known_fields',message='请保存我确认的志愿活动信息：名称改为校园环保小队，组织名称改为环保协会，联系方式改为站内找小林。其他字段保持原值。',expect='fields',values={'title':'校园环保小队','organization_name':'环保协会','contact':'站内找小林'}),
 dict(id='missing_place',message='各岗位的地点还没有确定，请先指出缺失条件，不要编造地址。',remove_location=True,expect='missing_location'),
 dict(id='staff_plan',message='请给出一个清洁、宣传和摄影分工的方案建议，总共二十名志愿者。请解释人数分配理由，等我采纳再修改岗位。',review=True,expect='review'),
 dict(id='headcount',message='我计划招募二十名志愿者，但当前岗位总人数好像不一致。请评估人数问题并给出可采纳的修正建议，不要直接改人数。',review=True,mismatch=True,expect='headcount'),
 dict(id='end_earlier',message='请暂存志愿活动的修改：一月五日结束时间提前到下午三点，两个岗位的时间都先保持不动，指出会影响哪些安排。',expect='end'),
 dict(id='deadline_conflict',message='请暂存志愿活动的修改：报名截止改为2030年1月5日下午三点，岗位仍是下午两点开始。保留这个草稿并指出冲突，不要发布。',expect='deadline'),
 dict(id='minutes_conflict',message='请暂存志愿活动的修改：清洁岗预计服务分钟改成180，实际岗位时段仍是14点到16点。请指出不合理之处，不要调整时段。',expect='minutes'),
 dict(id='rename',message='把清洁岗改名为物料整理岗，职责改为整理公益活动物料，人数和时段不变。请保存这个志愿活动草稿。',expect='rename'),
 dict(id='reorder',message='请把志愿活动草稿中的摄影岗放在第一位、清洁岗放第二位。只调整显示顺序，岗位人数、职责和时段保持不变。',expect='reorder'),
 dict(id='add_job',message='请保存志愿活动草稿：增加宣传岗两人，负责介绍环保知识，要求能按时到场，地点紫金港活动中心，2030年1月5日14点到16点，预计120分钟，按实际服务核验。计划总招募人数改为22人。原有岗位保持不变。',expect='add'),
 dict(id='remove_job',message='请保存志愿活动草稿：删除摄影岗，保留清洁岗原来的十二个名额和时段，计划招募总人数改为十二人。',expect='remove'),
 dict(id='clear_contact',message='请清除志愿活动草稿的联系方式，该信息尚未确定。其他字段不要改，提示我后续补齐。',expect='clear_contact'),
 dict(id='clear_total',message='计划招募人数还没定，请清除志愿活动草稿的总招募人数约束，保持岗位名额不动。',expect='clear_target'),
 dict(id='accept',message='请评估活动执行安排，给出至少一项带依据、可采纳到草稿的具体修改建议，先不要改正式字段。',review=True,expect='accept'),
 dict(id='reject',message='请评估当前活动，为岗位职责或活动说明提出至少一项具体修改建议，等待我决定是否采纳。',review=True,expect='reject'),
 dict(id='stale',message='请评估草稿，提出至少一条带字段修改内容的建议，等我确认，不要直接改动。',review=True,expect='stale'),
 dict(id='equipment_unknown',message='摄影岗的设备、集合点和培训安排还没确定。请评估并列出需我确认的条件，不要声称已经解决。',review=True,expect='review'),
 dict(id='no_unrequested_shift',message='请保存志愿活动草稿：活动开始时间提前到2030年1月5日13点，其余字段不变。请评估是否还需要调整集合或培训安排，先不要自动改岗位时间。',expect='start'),
 dict(id='cancel_inflight',message='请把志愿活动草稿名称改为环保协作体验日并暂存，然后解释本次修改对筹备安排的影响。',expect='cancel'),
 dict(id='cross_account',message='请读取我当前的志愿活动草稿，核对已确认的条件，不要修改草稿或发布。',expect='cross_account'),
]


JOB_TEXTS=[
 ('video','影像记录岗','为活动拍摄短视频和宣传片','需要会拍视频'),
 ('photo','摄影记录岗','拍摄现场照片','需要会摄影'),
 ('edit','后期制作岗','剪辑活动影片和短视频','需要视频剪辑能力'),
 ('write','宣传文案岗','撰写招募推文和宣传文字','需要文案写作'),
 ('design','视觉物料岗','制作活动海报与宣传图','需要平面设计'),
 ('speak','现场讲解岗','向参观者介绍校园展览','需要讲解表达'),
 ('guide','路线引导岗','帮助来访同学找到活动场地','需要现场引导'),
 ('support','物料支持岗','搬运、整理物料，协助布场','需要活动支持'),
 ('environment','环保行动','校园垃圾分类和环境清理','能按时参与'),
 ('education','助学活动','为学生开展学习辅导','能按时参与'),
 ('culture','校园文化活动','介绍传统文化与艺术','能按时参与'),
 ('science','科普活动','介绍科学知识与实验','能按时参与'),
 ('camera','拍摄设备岗','拍摄活动宣传片','必须会拍视频，必须自备相机'),
]

# Deliberately varied language, including nearby-but-different skills and negatives.
ANNOTATED_PROFILES=[
 ('拍过社团宣传片','video'),('会拍视频','video'),('做过校园短片拍摄','video'),
 ('平时用相机拍照','photo'),('会摄影','photo'),('拍过活动照片','photo'),
 ('会剪片子','edit'),('做过视频后期','edit'),('能剪辑短视频','edit'),
 ('写过公众号推文','write'),('能写宣传文字','write'),('会文案写作','write'),
 ('做过社团海报','design'),('会平面设计','design'),('能制作宣传图','design'),
 ('做过展览讲解','speak'),('擅长向观众介绍展品','speak'),('有讲解经验','speak'),
 ('做过迎新带路','guide'),('会现场引导','guide'),('能帮助来访者找场地','guide'),
 ('参加过活动布场','support'),('能搬运整理物料','support'),('做过活动支持','support'),
 ('对环境保护和垃圾分类感兴趣','environment'),('喜欢教育和助学','education'),('对传统文化感兴趣','culture'),('喜欢科学知识和科普','science'),
 ('会拍视频，但是没有相机','video'),('不会拍视频，只会拍照','photo'),
]


def candidate(identifier,title,description,requirements):
    return dict(content_type='volunteer',resource_id='evaluation-'+identifier,job_id=identifier,title=title,subtitle=title,description=description,requirements=requirements,location='紫金港',
        starts_at='2030-01-05T14:00:00+08:00',ends_at='2030-01-05T16:00:00+08:00',opens_at='2030-01-01T08:00:00+08:00',closes_at='2030-01-04T18:00:00+08:00',remaining_capacity=5,href='#/volunteers/evaluation-'+identifier)


JOBS=[candidate(*row) for row in JOB_TEXTS]
