import { Router, type IRouter } from "express";
import healthRouter from "./health";
import processRouter from "./process";

const router: IRouter = Router();

router.use(healthRouter);
router.use(processRouter);

export default router;
