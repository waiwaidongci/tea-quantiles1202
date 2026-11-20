export const ROLES=['admin','analyst','viewer'];
export const STATES=['queued','running','completed','failed'];
export const STATE_LABELS={queued:'等待计算',running:'计算进行中',completed:'已完成',failed:'失败需修复'};
export const CALIBRATION_STATES=['queued','running','completed','infeasible','failed','superseded'];
export const CALIBRATION_LABELS={queued:'等待计算',running:'计算进行中',completed:'已完成并生效',infeasible:'两轴无解，保留旧版',failed:'失败需修复',superseded:'已被较新申请取代'};
